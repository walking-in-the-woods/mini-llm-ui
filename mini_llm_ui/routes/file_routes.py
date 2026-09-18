"""Маршруты загрузки и удаления вложений."""

from __future__ import annotations

import logging

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    render_template,
    request,
)
from flask.typing import ResponseReturnValue

from mini_llm_ui import constants
from mini_llm_ui.config import AppConfig
from mini_llm_ui.db import get_request_connection
from mini_llm_ui.exceptions import FileValidationError
from mini_llm_ui.models import (
    add_attachment,
    delete_attachment,
    get_attachment_total_size,
    get_chat,
)
from mini_llm_ui.security import make_htmx_error_response
from mini_llm_ui.services.file_service import read_text_file

_LOG = logging.getLogger(__name__)

file_blueprint = Blueprint('file', __name__)

_APP_CONFIG_KEY = 'APP_CONFIG'


def _app_config() -> AppConfig:
    """Типизированный доступ к app_config из current_app.config."""
    return current_app.config[_APP_CONFIG_KEY]  # type: ignore[no-any-return]


def _upload_error_response(message: str) -> ResponseReturnValue:
    """Ошибка загрузки идёт в отдельный блок #upload-error, не в список чипов."""
    return make_htmx_error_response(
        message,
        status=400,
        target_selector='#upload-error',
    )


@file_blueprint.route('/chat/<int:chat_id>/upload', methods=['POST'])
def upload(chat_id: int) -> ResponseReturnValue:
    """Принимает .md/.txt, валидирует и сохраняет как вложение чата.

    Проверки:
      - чат существует;
      - файл передан;
      - расширение и размер проходят валидацию в file_service;
      - суммарный размер вложений чата не превышает лимит.
    """
    app_config = _app_config()
    connection = get_request_connection(app_config)

    if get_chat(connection, chat_id) is None:
        abort(404)

    uploaded_file = request.files.get('file')
    if uploaded_file is None:
        return _upload_error_response('Файл не получен')

    try:
        filename, content = read_text_file(uploaded_file, app_config)
    except FileValidationError as validation_error:
        return _upload_error_response(str(validation_error))

    new_size_bytes = len(content.encode('utf-8'))
    current_size_bytes = get_attachment_total_size(connection, chat_id)
    if current_size_bytes + new_size_bytes > app_config.max_attachment_total_size_bytes:
        limit_kb = app_config.max_attachment_total_size_bytes // 1024
        return _upload_error_response(
            constants.ERROR_ATTACHMENT_TOTAL_TEMPLATE.format(limit_kb=limit_kb)
        )

    attachment_id = add_attachment(connection, chat_id, filename, content)
    return render_template(
        'partials/attachment_chip.html',
        chat_id=chat_id,
        attachment={'id': attachment_id, 'filename': filename},
    )


@file_blueprint.route(
    '/chat/<int:chat_id>/attachment/<int:attachment_id>/delete',
    methods=['POST'],
)
def delete_attachment_route(chat_id: int, attachment_id: int) -> ResponseReturnValue:
    """Удаляет вложение. Клиент просто убирает чип из DOM (пустой ответ)."""
    app_config = _app_config()
    connection = get_request_connection(app_config)

    delete_attachment(connection, attachment_id, chat_id)
    return Response(status=204)
