"""Настройка логирования приложения.

Вызывается один раз в create_app(). Все модули используют
`logging.getLogger(__name__)` — иерархия имён естественно строится
из имени пакета.
"""

from __future__ import annotations

import logging
import sys
from typing import Final

_LOG_FORMAT: Final[str] = '%(asctime)s %(levelname)-8s %(name)s: %(message)s'
_DATE_FORMAT: Final[str] = '%Y-%m-%d %H:%M:%S'

_CONFIGURED: bool = False


def configure_logging(level: int = logging.INFO) -> None:
    """Настраивает root logger однократно.

    Идемпотентна: повторный вызов ничего не делает, чтобы не плодить
    дублирующиеся обработчики при пересоздании приложения в тестах.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)

    # Werkzeug шумит на INFO по каждому запросу. На N100 с polling
    # каждые 700 мс это заливает stderr — оставляем только WARNING.
    logging.getLogger('werkzeug').setLevel(logging.WARNING)

    _CONFIGURED = True


def reset_logging_for_tests() -> None:
    """Сбрасывает флаг конфигурации. Только для тестов."""
    global _CONFIGURED
    _CONFIGURED = False
