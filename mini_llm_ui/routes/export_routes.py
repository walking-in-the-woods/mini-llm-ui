"""Экспорт сообщения в .md-файл."""

from __future__ import annotations

from flask import Blueprint, Response, abort, current_app
from flask.typing import ResponseReturnValue

from mini_llm_ui.config import AppConfig
from mini_llm_ui.db import get_request_connection
from mini_llm_ui.models import get_message

export_blueprint = Blueprint('export', __name__)

_APP_CONFIG_KEY = 'APP_CONFIG'


def _app_config() -> AppConfig:
    """Типизированный доступ к app_config из current_app.config."""
    return current_app.config[_APP_CONFIG_KEY]  # type: ignore[no-any-return]


@export_blueprint.route(
    '/chat/<int:chat_id>/message/<int:message_id>/export',
)
def export_message(chat_id: int, message_id: int) -> ResponseReturnValue:
    """Отдаёт содержимое сообщения как .md-файл для скачивания.

    chat_id в URL — чтобы нельзя было вытащить сообщение из чужого чата
    по угаданному id (даже в однопользовательском сценарии это чище).
    """
    app_config = _app_config()
    connection = get_request_connection(app_config)

    message = get_message(connection, message_id)
    if message is None or message['chat_id'] != chat_id:
        abort(404)

    filename = f'message_{message_id}.md'
    return Response(
        str(message['content'] or ''),
        mimetype='text/markdown; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )
