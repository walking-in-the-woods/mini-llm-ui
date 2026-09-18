"""Слой доступа к SQLite.

Каждая функция принимает явный connection или AppConfig. Это делает
модуль тестируемым без глобальных патчей: тест подсовывает свой
AppConfig с временными путями.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from flask import g

from mini_llm_ui.config import AppConfig

_LOG = logging.getLogger(__name__)

_SCHEMA: Final[str] = """
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT 'Новый чат',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL DEFAULT '',
    html_content TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id, id);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_attachments_chat_id ON attachments(chat_id, id);
"""

_ORPHANED_MARKER_HTML_TEMPLATE: Final[str] = '<p><em>{marker}</em></p>'


def _open_connection(database_path: Path) -> sqlite3.Connection:
    """Открывает соединение с нужными PRAGMA.

    check_same_thread=False нужен, потому что фоновый поток стриминга
    пишет в БД отдельно от Flask-запроса. Параллельные записи
    сериализуются busy_timeout.
    """
    connection = sqlite3.connect(str(database_path), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    connection.execute('PRAGMA synchronous = NORMAL')
    connection.execute('PRAGMA cache_size = -2000')  # ~2 МБ кеша
    connection.execute('PRAGMA temp_store = MEMORY')
    connection.execute('PRAGMA busy_timeout = 5000')  # 5 сек на блокировку
    return connection


def open_standalone_connection(
    app_config: AppConfig,
) -> sqlite3.Connection:
    """Соединение вне контекста Flask-запроса.

    Используется фоновым потоком стриминга, где нет request context.
    Вызывающая сторона обязана закрыть соединение.
    """
    return _open_connection(app_config.database_path)


def get_request_connection(app_config: AppConfig) -> sqlite3.Connection:
    """Соединение, привязанное к текущему Flask-запросу.

    Переиспользуется между вызовами внутри одного запроса. Закрывается
    автоматически через teardown_appcontext (см. close_request_connection).
    """
    existing = g.get('db')
    if isinstance(existing, sqlite3.Connection):
        return existing

    connection = _open_connection(app_config.database_path)
    g.db = connection
    return connection


def close_request_connection(
    _exception: BaseException | None = None,
) -> None:
    """teardown_appcontext-хук: закрывает соединение, если оно было открыто."""
    connection = g.pop('db', None)
    if isinstance(connection, sqlite3.Connection):
        connection.close()


def initialize_database(app_config: AppConfig) -> None:
    """Создаёт директории и таблицы. Идемпотентно."""
    app_config.ensure_directories()
    connection = _open_connection(app_config.database_path)
    try:
        connection.execute('PRAGMA journal_mode = WAL')
        connection.executescript(_SCHEMA)
        connection.commit()
    finally:
        connection.close()


def mark_orphaned_assistant_messages(
    app_config: AppConfig,
    marker_text: str,
) -> int:
    """Помечает пустые assistant-сообщения, оставшиеся после рестарта.

    Стрим пишет финальный контент только в конце; если процесс упал
    во время генерации, в БД останется пустая строка. Такие сообщения
    заменяются на видимый маркер, чтобы UI не показывал пустоту.

    Возвращает количество затронутых записей.
    """
    marker_html = _ORPHANED_MARKER_HTML_TEMPLATE.format(marker=marker_text)
    connection = _open_connection(app_config.database_path)
    try:
        cursor = connection.execute(
            'UPDATE messages SET content = ?, html_content = ? '
            "WHERE role = 'assistant' AND content = ''",
            (marker_text, marker_html),
        )
        connection.commit()
        return cursor.rowcount or 0
    finally:
        connection.close()


@contextmanager
def standalone_cursor(
    app_config: AppConfig,
) -> Iterator[sqlite3.Cursor]:
    """Контекстный менеджер: соединение + курсор + commit.

    Упрощает фоновый код, где нужно «открыл-выполнил-закрыл».
    """
    connection = _open_connection(app_config.database_path)
    try:
        cursor = connection.cursor()
        try:
            yield cursor
            connection.commit()
        finally:
            cursor.close()
    finally:
        connection.close()
