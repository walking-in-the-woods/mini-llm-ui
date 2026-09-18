"""Числовые и строковые константы приложения.

Здесь только значения, не зависящие от окружения. Всё, что читается
из переменных окружения, живёт в config.py.
"""

from __future__ import annotations

from typing import Final

# --- Сетевые параметры dev-сервера ----------------------------------------

LISTEN_HOST: Final[str] = '127.0.0.1'
LISTEN_PORT: Final[int] = 5000

# --- Хосты, принимаемые в Host-заголовке (анти-DNS-rebinding) ------------

ALLOWED_HOSTS: Final[frozenset[str]] = frozenset(
    {
        '127.0.0.1',
        'localhost',
        '::1',
        '[::1]',
    }
)

# --- Ограничения на файлы и историю ---------------------------------------

MAX_FILE_SIZE_BYTES: Final[int] = 256 * 1024
MAX_ATTACHMENT_TOTAL_SIZE_BYTES: Final[int] = 100 * 1024
MAX_REQUEST_SIZE_BYTES: Final[int] = 4 * 1024 * 1024
MAX_HISTORY_MESSAGES: Final[int] = 20
ALLOWED_FILE_EXTENSIONS: Final[frozenset[str]] = frozenset({'.md', '.txt'})

# --- Стриминг -------------------------------------------------------------

STREAM_POLL_INTERVAL_MS: Final[int] = 700
STREAM_CLEANUP_DELAY_SECONDS: Final[float] = 60.0
STREAM_CLEANUP_DELAY_AFTER_DB_FAIL_SECONDS: Final[float] = 300.0
STREAM_CANCEL_MARKER: Final[str] = '\n\n_\\[генерация остановлена\\]_'

# --- Пути внутри data/ ----------------------------------------------------

DATA_DIR_NAME: Final[str] = 'data'
UPLOADS_DIR_NAME: Final[str] = 'uploads'
RECOVERY_DIR_NAME: Final[str] = 'recovery'
DATABASE_FILENAME: Final[str] = 'chat.db'
SECRET_KEY_FILENAME: Final[str] = 'secret_key'
RECOVERY_FILE_TEMPLATE: Final[str] = 'msg_{message_id}.md'

# --- Сообщения об ошибках (для UI) ----------------------------------------

ERROR_FILE_NOT_SELECTED: Final[str] = 'Файл не выбран'
ERROR_FILE_TOO_LARGE_TEMPLATE: Final[str] = (
    'Файл слишком большой (максимум {limit_kb} КБ)'
)
ERROR_FILE_EXTENSION_TEMPLATE: Final[str] = 'Недопустимый формат. Разрешены: {allowed}'
ERROR_ATTACHMENT_TOTAL_TEMPLATE: Final[str] = (
    'Превышен общий лимит вложений чата ({limit_kb} КБ).'
)
ERROR_STREAM_BUSY: Final[str] = 'Дождитесь завершения текущей генерации.'
ERROR_ORPHANED_ASSISTANT_MARKER: Final[str] = '[прервано перезапуском]'
ERROR_STREAM_FAILURE_TEMPLATE: Final[str] = '⚠️ Ошибка генерации: {error}'
