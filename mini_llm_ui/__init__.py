"""mini-llm-ui — компактный локальный интерфейс к моделям Ollama.

Публичный API пакета — только create_app(). Всё остальное — внутренняя
реализация и не является частью контракта.

ВАЖНО: __version__ определяется ДО импорта app. Иначе циклический
импорт: app.py делает `from mini_llm_ui import __version__`, а этот
модуль сначала пытается импортировать app.
"""

from __future__ import annotations

__version__ = '1.0.0'

from mini_llm_ui.app import create_app

__all__ = ['create_app']
