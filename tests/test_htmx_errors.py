"""Ошибки HTMX: 4xx с HX-Retarget, откат сообщений при гонке reserve."""

from __future__ import annotations

import io
import re
import time

import pytest
from flask import Flask
from flask.testing import FlaskClient

from mini_llm_ui.services.stream_manager import StreamManager
from tests.conftest import create_chat


def test_conflict_response_is_409_with_retarget(
    slow_client: FlaskClient,
) -> None:
    """Второй POST во время активного стрима → 409 + HX-Retarget.

    Использует slow_client: с быстрым fake первый стрим успевает
    завершиться до второго POST, и конфликт не воспроизводится.
    """
    chat_id = create_chat(slow_client)
    slow_client.post(f'/chat/{chat_id}/send', data={'content': 'first'})

    second_response = slow_client.post(
        f'/chat/{chat_id}/send',
        data={'content': 'second'},
    )
    assert second_response.status_code == 409
    assert second_response.headers.get('HX-Retarget') == '#chat-error'
    assert 'Дождитесь'.encode() in second_response.data


def test_upload_error_is_400_with_retarget(client: FlaskClient) -> None:
    chat_id = create_chat(client)
    response = client.post(f'/chat/{chat_id}/upload', data={})
    assert response.status_code == 400
    assert response.headers.get('HX-Retarget') == '#upload-error'
    assert b'error' in response.data


def test_upload_rejects_disallowed_extension(client: FlaskClient) -> None:
    chat_id = create_chat(client)
    payload = {'file': (io.BytesIO(b'echo hi'), 'evil.sh')}
    response = client.post(
        f'/chat/{chat_id}/upload',
        data=payload,
        content_type='multipart/form-data',
    )
    assert response.status_code == 400
    assert response.headers.get('HX-Retarget') == '#upload-error'
    assert 'формат'.encode() in response.data


def test_upload_accepts_markdown(client: FlaskClient) -> None:
    chat_id = create_chat(client)
    payload = {'file': (io.BytesIO(b'# Title\n\ntext'), 'notes.md')}
    response = client.post(
        f'/chat/{chat_id}/upload',
        data=payload,
        content_type='multipart/form-data',
    )
    assert response.status_code == 200
    assert b'notes.md' in response.data


def test_rollback_on_reserve_race(
    client: FlaskClient,
    app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Гонка между пре-чеком и try_reserve: оба сообщения откатываются.

    Имитируем сценарий, когда has_active_stream вернул False, но
    try_reserve отказал (кто-то стартовал между вызовами).
    """
    stream_manager: StreamManager = app.extensions['stream_manager']
    monkeypatch.setattr(stream_manager, 'has_active_stream', lambda _chat_id: False)
    monkeypatch.setattr(stream_manager, 'try_reserve', lambda _chat_id, _mid: False)

    chat_id = create_chat(client)
    response = client.post(f'/chat/{chat_id}/send', data={'content': 'ghost'})
    assert response.status_code == 409
    assert response.headers.get('HX-Retarget') == '#chat-error'

    # В БД не осталось ни user-сообщения, ни placeholder-ассистента,
    # ни следа переименования чата.
    page = client.get(f'/chat/{chat_id}')
    assert b'ghost' not in page.data
    assert 'не запущено'.encode() not in page.data
    assert 'Новый чат'.encode() in page.data


def test_stop_is_idempotent_after_completion(client: FlaskClient) -> None:
    """Если стрим уже завершён, POST /stop не ломается."""
    chat_id = create_chat(client)
    client.post(f'/chat/{chat_id}/send', data={'content': 'hi'})
    time.sleep(0.3)

    page = client.get(f'/chat/{chat_id}')
    match = re.search(rb'id="message-(\d+)"', page.data)
    assert match is not None
    message_id = int(match.group(1))

    stop_response = client.post(f'/chat/{chat_id}/message/{message_id}/stop')
    # Стрим уже done — роут отдаёт message.html с 200.
    assert stop_response.status_code == 200


def test_edit_assistant_message_is_forbidden(client: FlaskClient) -> None:
    """Ответ модели редактировать нельзя — ни через GET, ни через POST.

    UI скрывает кнопку ✏️ у assistant-сообщений, но защита должна
    быть и на сервере: прямой запрос по URL возвращает 403.
    """
    chat_id = create_chat(client)
    client.post(f'/chat/{chat_id}/send', data={'content': 'hi'})
    time.sleep(0.3)

    page = client.get(f'/chat/{chat_id}')
    ids = re.findall(rb'id="message-(\d+)"', page.data)
    # Должно быть два сообщения: user (первое) и assistant (второе).
    assert len(ids) >= 2
    assistant_message_id = int(ids[1])

    edit_response = client.get(f'/chat/{chat_id}/message/{assistant_message_id}/edit')
    assert edit_response.status_code == 403

    save_response = client.post(
        f'/chat/{chat_id}/message/{assistant_message_id}/save',
        data={'content': 'forged'},
    )
    assert save_response.status_code == 403

    # Контент не изменился.
    page_after = client.get(f'/chat/{chat_id}')
    assert b'forged' not in page_after.data
