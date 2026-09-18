"""Чтение и валидация загруженных текстовых файлов."""

from __future__ import annotations

from typing import Final

from werkzeug.datastructures import FileStorage

from mini_llm_ui import constants
from mini_llm_ui.config import AppConfig
from mini_llm_ui.exceptions import FileValidationError

_UTF8_DECODE_ERRORS: Final[str] = 'replace'


def read_text_file(
    uploaded_file: FileStorage,
    app_config: AppConfig,
) -> tuple[str, str]:
    """Читает загруженный .md или .txt, возвращает (имя, содержимое).

    Проверки:
      - имя файла присутствует;
      - расширение входит в allow-list (.md, .txt);
      - размер не превышает max_file_size_bytes;
      - декодирование — UTF-8 с заменой невалидных байт на U+FFFD
        (пользователь увидит испорченный символ, а не 500).

    Кидает FileValidationError на любом нарушении.
    """
    filename = uploaded_file.filename or ''
    if not filename:
        raise FileValidationError(constants.ERROR_FILE_NOT_SELECTED)

    extension = _extract_extension(filename)
    if extension not in app_config.allowed_file_extensions:
        allowed = ', '.join(sorted(app_config.allowed_file_extensions))
        raise FileValidationError(
            constants.ERROR_FILE_EXTENSION_TEMPLATE.format(allowed=allowed)
        )

    # Читаем на байт больше лимита, чтобы отличить «ровно лимит» от «сверх».
    raw_bytes = uploaded_file.read(app_config.max_file_size_bytes + 1)
    if len(raw_bytes) > app_config.max_file_size_bytes:
        limit_kb = app_config.max_file_size_bytes // 1024
        raise FileValidationError(
            constants.ERROR_FILE_TOO_LARGE_TEMPLATE.format(limit_kb=limit_kb)
        )

    content = raw_bytes.decode('utf-8', errors=_UTF8_DECODE_ERRORS)
    return filename, content


def _extract_extension(filename: str) -> str:
    """Возвращает расширение в нижнем регистре с точкой.

    'README.MD' → '.md'. Если точки нет — пустая строка.
    """
    if '.' not in filename:
        return ''
    return '.' + filename.rsplit('.', 1)[-1].lower()
