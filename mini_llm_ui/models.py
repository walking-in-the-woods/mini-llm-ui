"""Операции с БД: чаты, сообщения, вложения.

Модуль не зависит от Flask. Все функции принимают соединение
явно, что позволяет использовать их и из request-контекста, и из
фонового потока стриминга.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Final, cast

_LOG = logging.getLogger(__name__)

_DEFAULT_CHAT_TITLE: Final[str] = 'Новый чат'
_MAX_TITLE_LENGTH: Final[int] = 60


def _last_inserted_id(cursor: sqlite3.Cursor) -> int:
    """Возвращает lastrowid, проверяя что он не None.

    sqlite3 типизирует lastrowid как int | None. None означает, что
    INSERT не произвёл строку — это программная ошибка вызывающего кода.
    """
    last_id = cursor.lastrowid
    if last_id is None:
        raise RuntimeError('INSERT did not produce a row id')
    return int(last_id)


# ---------- Chats ---------------------------------------------------------


def create_chat(
    connection: sqlite3.Connection,
    title: str = _DEFAULT_CHAT_TITLE,
) -> int:
    """Создаёт чат и возвращает его id."""
    cursor = connection.execute(
        'INSERT INTO chats (title) VALUES (?)',
        (title,),
    )
    connection.commit()
    return _last_inserted_id(cursor)


def list_chats(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    """Все чаты, свежие — первыми."""
    cursor = connection.execute('SELECT * FROM chats ORDER BY updated_at DESC, id DESC')
    return list(cursor.fetchall())


def get_chat(
    connection: sqlite3.Connection,
    chat_id: int,
) -> sqlite3.Row | None:
    """Чат по id или None."""
    cursor = connection.execute('SELECT * FROM chats WHERE id = ?', (chat_id,))
    return cast('sqlite3.Row | None', cursor.fetchone())


def delete_chat(connection: sqlite3.Connection, chat_id: int) -> None:
    """Удаляет чат. Сообщения и вложения уходят каскадом."""
    connection.execute('DELETE FROM chats WHERE id = ?', (chat_id,))
    connection.commit()


def rename_chat(
    connection: sqlite3.Connection,
    chat_id: int,
    title: str,
) -> None:
    """Переименовывает чат и обновляет updated_at."""
    connection.execute(
        "UPDATE chats SET title = ?, updated_at = datetime('now', 'localtime') "
        'WHERE id = ?',
        (title, chat_id),
    )
    connection.commit()


def auto_title_from_first_message(
    connection: sqlite3.Connection,
    chat_id: int,
) -> None:
    """Переименовывает чат по первому user-сообщению.

    Работает только если чат всё ещё носит дефолтное имя — ручное
    переименование пользователем не перетирается.
    """
    chat = get_chat(connection, chat_id)
    if chat is None or chat['title'] != _DEFAULT_CHAT_TITLE:
        return

    cursor = connection.execute(
        "SELECT content FROM messages WHERE chat_id = ? AND role = 'user' "
        'ORDER BY id ASC LIMIT 1',
        (chat_id,),
    )
    first_message = cursor.fetchone()
    if first_message is None or not first_message['content']:
        return

    first_line = str(first_message['content']).strip().splitlines()[0]
    title = first_line[:_MAX_TITLE_LENGTH]
    if title:
        rename_chat(connection, chat_id, title)


# ---------- Messages ------------------------------------------------------


def add_message(
    connection: sqlite3.Connection,
    chat_id: int,
    role: str,
    content: str,
    html_content: str = '',
) -> int:
    """Добавляет сообщение и возвращает его id.

    Также обновляет updated_at родительского чата — это то, по чему
    сортируется список чатов в сайдбаре.
    """
    cursor = connection.execute(
        'INSERT INTO messages (chat_id, role, content, html_content) '
        'VALUES (?, ?, ?, ?)',
        (chat_id, role, content, html_content),
    )
    connection.execute(
        "UPDATE chats SET updated_at = datetime('now', 'localtime') WHERE id = ?",
        (chat_id,),
    )
    connection.commit()
    return _last_inserted_id(cursor)


def update_message(
    connection: sqlite3.Connection,
    message_id: int,
    content: str,
    html_content: str,
) -> None:
    """Обновляет содержимое сообщения.

    Используется двумя путями:
      - редактор сохраняет правки;
      - стриминг-воркер финализирует ответ ассистента.
    """
    connection.execute(
        'UPDATE messages SET content = ?, html_content = ? WHERE id = ?',
        (content, html_content, message_id),
    )
    connection.commit()


def delete_message(
    connection: sqlite3.Connection,
    message_id: int,
) -> None:
    """Удаляет сообщение.

    Используется для отката user + assistant при отказе try_reserve
    (гонка между пре-чеком и резервацией слота).
    """
    connection.execute('DELETE FROM messages WHERE id = ?', (message_id,))
    connection.commit()


def get_message(
    connection: sqlite3.Connection,
    message_id: int,
) -> sqlite3.Row | None:
    """Сообщение по id или None."""
    cursor = connection.execute('SELECT * FROM messages WHERE id = ?', (message_id,))
    return cast('sqlite3.Row | None', cursor.fetchone())


def get_messages(
    connection: sqlite3.Connection,
    chat_id: int,
) -> list[sqlite3.Row]:
    """Все сообщения чата в хронологическом порядке."""
    cursor = connection.execute(
        'SELECT * FROM messages WHERE chat_id = ? ORDER BY id ASC',
        (chat_id,),
    )
    return list(cursor.fetchall())


# ---------- Attachments ---------------------------------------------------


def add_attachment(
    connection: sqlite3.Connection,
    chat_id: int,
    filename: str,
    content: str,
) -> int:
    """Сохраняет текстовое вложение и возвращает его id."""
    cursor = connection.execute(
        'INSERT INTO attachments (chat_id, filename, content) VALUES (?, ?, ?)',
        (chat_id, filename, content),
    )
    connection.commit()
    return _last_inserted_id(cursor)


def get_attachments(
    connection: sqlite3.Connection,
    chat_id: int,
) -> list[sqlite3.Row]:
    """Метаданные вложений без содержимого — для отрисовки чипов в UI."""
    cursor = connection.execute(
        'SELECT id, chat_id, filename, created_at FROM attachments '
        'WHERE chat_id = ? ORDER BY id ASC',
        (chat_id,),
    )
    return list(cursor.fetchall())


def get_attachment_contents(
    connection: sqlite3.Connection,
    chat_id: int,
) -> list[sqlite3.Row]:
    """Полное содержимое вложений — для передачи в модель."""
    cursor = connection.execute(
        'SELECT filename, content FROM attachments WHERE chat_id = ? ORDER BY id ASC',
        (chat_id,),
    )
    return list(cursor.fetchall())


def get_attachment_total_size(
    connection: sqlite3.Connection,
    chat_id: int,
) -> int:
    """Суммарный размер вложений чата в байтах.

    Считается SQL-функцией LENGTH(), а не в Python, чтобы не гонять
    содержимое через память дважды.
    """
    cursor = connection.execute(
        'SELECT COALESCE(SUM(LENGTH(content)), 0) AS total '
        'FROM attachments WHERE chat_id = ?',
        (chat_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return 0
    return int(row['total'] or 0)


def delete_attachment(
    connection: sqlite3.Connection,
    attachment_id: int,
    chat_id: int,
) -> None:
    """Удаляет вложение. chat_id в WHERE — защита от удаления чужого."""
    connection.execute(
        'DELETE FROM attachments WHERE id = ? AND chat_id = ?',
        (attachment_id, chat_id),
    )
    connection.commit()
