"""Маршруты работы с чатами: список, просмотр, отправка, стриминг, стоп."""

from __future__ import annotations

import logging
from typing import Any

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    url_for,
)
from flask.typing import ResponseReturnValue

from mini_llm_ui import constants
from mini_llm_ui.config import AppConfig
from mini_llm_ui.db import get_request_connection
from mini_llm_ui.models import (
    add_message,
    auto_title_from_first_message,
    create_chat,
    delete_message,
    get_attachment_contents,
    get_attachments,
    get_chat,
    get_message,
    get_messages,
    list_chats,
    update_message,
)
from mini_llm_ui.models import (
    delete_chat as delete_chat_row,
)
from mini_llm_ui.security import make_htmx_error_response
from mini_llm_ui.services.markdown_service import render_markdown
from mini_llm_ui.services.ollama_service import build_prompt_messages
from mini_llm_ui.services.stream_manager import StreamManager

_LOG = logging.getLogger(__name__)

chat_blueprint = Blueprint('chat', __name__)

_APP_CONFIG_KEY = 'APP_CONFIG'
_STREAM_MANAGER_KEY = 'stream_manager'


# ---------- Вспомогательные рендеры ---------------------------------------


def _busy_response() -> ResponseReturnValue:
    """Ответ 409 с HX-Retarget на попытку отправить сообщение во время стрима."""
    return make_htmx_error_response(
        constants.ERROR_STREAM_BUSY,
        status=409,
        target_selector='#chat-error',
    )


def _app_config() -> AppConfig:
    """Типизированный доступ к app_config из current_app.config."""
    return current_app.config[_APP_CONFIG_KEY]  # type: ignore[no-any-return]


def _stream_manager() -> StreamManager:
    """Типизированный доступ к stream_manager из current_app.extensions."""
    return current_app.extensions[_STREAM_MANAGER_KEY]  # type: ignore[no-any-return]


def _build_active_streams_index(
    messages: list[Any],
    stream_manager: StreamManager,
) -> dict[int, dict[str, Any]]:
    """Собирает карту активных стримов для шаблона index.html.

    Возвращает {message_id: {'content': str, 'stopping': bool, 'completed': bool}}.

    Включает два случая:
      - активный стрим (в том числе с уже запрошенной отменой);
      - завершённый стрим, по которому в БД контент пуст
        (например, персист ещё не отработал или упал — берём из памяти).
    """
    index: dict[int, dict[str, Any]] = {}
    for message in messages:
        if message['role'] != 'assistant':
            continue
        snapshot = stream_manager.get_snapshot(int(message['id']))
        if snapshot is None:
            continue
        if not snapshot.done:
            index[int(message['id'])] = {
                'content': snapshot.content,
                'stopping': snapshot.cancel_requested,
                'completed': False,
            }
        elif not message['content'] and snapshot.content:
            index[int(message['id'])] = {
                'content': snapshot.content,
                'stopping': False,
                'completed': True,
            }
    return index


# ---------- Маршруты ------------------------------------------------------


@chat_blueprint.route('/')
def index() -> ResponseReturnValue:
    """Редирект на первый чат или отрисовка пустого состояния."""
    app_config = _app_config()
    connection = get_request_connection(app_config)
    chats = list_chats(connection)

    if chats:
        return redirect(url_for('chat.view_chat', chat_id=int(chats[0]['id'])))

    return render_template(
        'index.html',
        chats=[],
        active_chat=None,
        messages=[],
        attachments=[],
        active_streams={},
        model=app_config.ollama_model,
    )


@chat_blueprint.route('/chat/<int:chat_id>')
def view_chat(chat_id: int) -> ResponseReturnValue:
    """Отрисовка конкретного чата со всеми сообщениями."""
    app_config = _app_config()
    stream_manager = _stream_manager()
    connection = get_request_connection(app_config)

    chat = get_chat(connection, chat_id)
    if chat is None:
        abort(404)

    messages = get_messages(connection, chat_id)
    return render_template(
        'index.html',
        chats=list_chats(connection),
        active_chat=chat,
        messages=messages,
        attachments=get_attachments(connection, chat_id),
        active_streams=_build_active_streams_index(messages, stream_manager),
        model=app_config.ollama_model,
    )


@chat_blueprint.route('/chat/new', methods=['POST'])
def new_chat() -> ResponseReturnValue:
    """Создание нового пустого чата и редирект в него."""
    app_config = _app_config()
    connection = get_request_connection(app_config)

    chat_id = create_chat(connection)
    return redirect(url_for('chat.view_chat', chat_id=chat_id))


@chat_blueprint.route('/chat/<int:chat_id>/delete', methods=['POST'])
def delete_chat(chat_id: int) -> ResponseReturnValue:
    """Удаление чата со всеми сообщениями."""
    app_config = _app_config()
    connection = get_request_connection(app_config)

    delete_chat_row(connection, chat_id)
    return redirect(url_for('chat.index'))


@chat_blueprint.route('/chat/<int:chat_id>/send', methods=['POST'])
def send_message(chat_id: int) -> ResponseReturnValue:
    """Отправка пользовательского сообщения и запуск стрима ответа.

    Порядок операций критичен:
      1. Пре-чек has_active_stream до любых записей в БД.
      2. Запись user-сообщения.
      3. Сборка промпта (до создания placeholder-ассистента).
      4. Резервация слота стрима.
      5. Только после успешной резервации — placeholder-ассистент.
      6. Запуск воркера.
      7. Автозаголовок — после успешного запуска.

    Если на шаге 4 отказ (гонка между пре-чеком и reserve) или на
    шаге 6 исключение — user и assistant сообщения откатываются,
    заголовок чата не трогается.
    """
    app_config = _app_config()
    stream_manager = _stream_manager()
    connection = get_request_connection(app_config)

    chat = get_chat(connection, chat_id)
    if chat is None:
        abort(404)

    content = (request.form.get('content') or '').strip()
    if not content:
        return Response(status=204)

    # Шаг 1: пре-чек. Закрывает основной сценарий без мусора в БД.
    if stream_manager.has_active_stream(chat_id):
        return _busy_response()

    # Шаг 2: user-сообщение.
    user_html = render_markdown(content)
    user_message_id = add_message(
        connection,
        chat_id,
        'user',
        content,
        user_html,
    )

    # Шаг 3: промпт — БЕЗ placeholder-ассистента. Иначе пустая строка
    # ушла бы в Ollama, что ломает генерацию.
    history = get_messages(connection, chat_id)
    attachments = get_attachment_contents(connection, chat_id)
    prompt_messages = build_prompt_messages(
        history,
        attachments,
        max_history=app_config.max_history_messages,
    )

    # Шаг 4: атомарная резервация слота.
    assistant_message_id = add_message(connection, chat_id, 'assistant', '')
    if not stream_manager.try_reserve(chat_id, assistant_message_id):
        # Гонка: между пре-чеком и reserve кто-то успел стартовать.
        delete_message(connection, assistant_message_id)
        delete_message(connection, user_message_id)
        return _busy_response()

    # Шаги 5–6: запуск воркера с откатом при любой ошибке запуска.
    try:
        stream_manager.start(
            assistant_message_id,
            app_config.ollama_model,
            prompt_messages,
        )
    except Exception:
        _LOG.exception(
            'Failed to start stream (chat_id=%s, message_id=%s)',
            chat_id,
            assistant_message_id,
        )
        stream_manager.release_reservation(assistant_message_id)
        delete_message(connection, assistant_message_id)
        delete_message(connection, user_message_id)
        raise

    # Шаг 7: автозаголовок — только при успешном запуске.
    auto_title_from_first_message(connection, chat_id)

    return render_template(
        'partials/message_pair.html',
        user_msg=get_message(connection, user_message_id),
        assistant_msg_id=assistant_message_id,
        chat_id=chat_id,
    )


@chat_blueprint.route('/chat/<int:chat_id>/message/<int:message_id>/poll')
def poll_message(chat_id: int, message_id: int) -> ResponseReturnValue:
    """Polling-эндпоинт стрима.

    Возвращает либо polling-фрагмент (пока стрим идёт), либо готовое
    сообщение (message.html). Если БД пуста, а в памяти контент есть —
    подставляет его из снапшота.
    """
    app_config = _app_config()
    stream_manager = _stream_manager()
    connection = get_request_connection(app_config)

    message = get_message(connection, message_id)
    if message is None or message['chat_id'] != chat_id:
        abort(404)

    snapshot = stream_manager.get_snapshot(message_id)

    if snapshot is not None and not snapshot.done:
        return render_template(
            'partials/message_polling.html',
            chat_id=chat_id,
            msg_id=message_id,
            content=snapshot.content,
            stopping=snapshot.cancel_requested,
            completed=False,
        )

    # Стрим завершён, но персист мог ещё не отработать (или упасть).
    # Если в БД пусто, а в памяти есть контент — отдаём из памяти.
    if (
        snapshot is not None
        and snapshot.done
        and not message['content']
        and snapshot.content
    ):
        return render_template(
            'partials/message.html',
            msg=_with_content_from_memory(message, snapshot.content),
        )

    return render_template('partials/message.html', msg=message)


@chat_blueprint.route(
    '/chat/<int:chat_id>/message/<int:message_id>/stop',
    methods=['POST'],
)
def stop_generation(chat_id: int, message_id: int) -> ResponseReturnValue:
    """Мягкая остановка стрима.

    Возвращает обновлённый фрагмент с уже накопленным текстом, чтобы
    пользователь не видел «мигание» пустого поля на следующем poll-тике.
    """
    app_config = _app_config()
    stream_manager = _stream_manager()
    connection = get_request_connection(app_config)

    message = get_message(connection, message_id)
    if message is None or message['chat_id'] != chat_id:
        abort(404)

    stream_manager.cancel(message_id)
    snapshot = stream_manager.get_snapshot(message_id)

    if snapshot is None:
        return render_template('partials/message.html', msg=message)

    if snapshot.done:
        # Стрим завершился, пока пользователь жал «стоп». Если персист
        # ещё не отработал, отдаём контент из памяти.
        if not message['content'] and snapshot.content:
            return render_template(
                'partials/message.html',
                msg=_with_content_from_memory(message, snapshot.content),
            )
        return render_template('partials/message.html', msg=message)

    # Активный стрим: сохраняем уже видимый контент.
    current_content = snapshot.content or str(message['content'] or '')
    return render_template(
        'partials/message_polling.html',
        chat_id=chat_id,
        msg_id=message_id,
        content=current_content,
        stopping=True,
        completed=False,
    )


@chat_blueprint.route('/chat/<int:chat_id>/message/<int:message_id>/view')
def view_message(chat_id: int, message_id: int) -> ResponseReturnValue:
    """Возвращает фрагмент сообщения в режиме чтения (отмена редактирования)."""
    app_config = _app_config()
    connection = get_request_connection(app_config)

    message = get_message(connection, message_id)
    if message is None or message['chat_id'] != chat_id:
        abort(404)
    return render_template('partials/message.html', msg=message)


@chat_blueprint.route('/chat/<int:chat_id>/message/<int:message_id>/edit')
def edit_message(chat_id: int, message_id: int) -> ResponseReturnValue:
    """Возвращает фрагмент сообщения в режиме редактирования.

    Редактировать можно только user-сообщения. Ответ модели —
    артефакт генерации, его нельзя перезаписывать. Даже если UI
    скрыл кнопку, прямой запрос по URL получает 403.
    """
    app_config = _app_config()
    connection = get_request_connection(app_config)

    message = get_message(connection, message_id)
    if message is None or message['chat_id'] != chat_id:
        abort(404)
    if message['role'] != 'user':
        abort(403)
    return render_template('partials/message_edit.html', msg=message)


@chat_blueprint.route(
    '/chat/<int:chat_id>/message/<int:message_id>/save',
    methods=['POST'],
)
def save_message(chat_id: int, message_id: int) -> ResponseReturnValue:
    """Сохраняет отредактированное сообщение и возвращает режим чтения.

    Та же защита, что и в edit_message: только user-сообщения.
    """
    app_config = _app_config()
    connection = get_request_connection(app_config)

    message = get_message(connection, message_id)
    if message is None or message['chat_id'] != chat_id:
        abort(404)
    if message['role'] != 'user':
        abort(403)

    new_content = (request.form.get('content') or '').strip()
    update_message(
        connection,
        message_id,
        new_content,
        render_markdown(new_content),
    )

    return render_template(
        'partials/message.html',
        msg=get_message(connection, message_id),
    )


# ---------- Вспомогательные функции уровня модуля -------------------------


def _with_content_from_memory(message: Any, content: str) -> dict[str, Any]:
    """Готовит «вью-модель» сообщения с контентом из памяти.

    Используется, когда стрим завершён, но персист ещё не отработал:
    в БД пусто, а в снапшоте есть текст. Возвращаем dict вместо
    sqlite3.Row — шаблон обращается к полям одинаково.
    """
    view: dict[str, Any] = dict(message)
    view['content'] = content
    view['html_content'] = render_markdown(content)
    return view
