"""Иерархия исключений приложения.

Делится на две группы:
  - MiniLlmUiError и наследники — ожидаемые ошибки, обрабатываются
    маршрутами и превращаются в осмысленные HTTP-ответы;
  - всё остальное (built-in исключения) — неожиданные сбои.

Такое разделение позволяет в errorhandler отделить «мы это
предвидели» от «сломалось что-то, что мы не предусмотрели».
"""

from __future__ import annotations


class MiniLlmUiError(Exception):
    """Базовый класс для всех ожидаемых ошибок приложения."""


class ValidationError(MiniLlmUiError):
    """Входные данные не прошли валидацию (файл, форма, параметры)."""


class FileValidationError(ValidationError):
    """Проблема с загруженным файлом: расширение, размер, кодировка."""


class ConflictError(MiniLlmUiError):
    """Операция конфликтует с текущим состоянием (например, занятый слот)."""


class StreamReservationError(ConflictError):
    """Не удалось зарезервировать слот стрима для чата."""


class PersistenceError(MiniLlmUiError):
    """Ошибка записи в БД или в файловое хранилище."""


class NotFoundError(MiniLlmUiError):
    """Запрошенный ресурс не существует."""
