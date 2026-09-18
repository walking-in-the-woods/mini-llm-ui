"""HTTP-маршруты приложения.

Пакет экспортирует единственную функцию register_blueprints, которую
вызывает create_app. Прямой импорт отдельных блюпринтов не нужен и
не поощряется — это деталь реализации.
"""

from __future__ import annotations

from flask import Flask

from mini_llm_ui.routes.chat_routes import chat_blueprint
from mini_llm_ui.routes.export_routes import export_blueprint
from mini_llm_ui.routes.file_routes import file_blueprint

__all__ = ['register_blueprints']


def register_blueprints(application: Flask) -> None:
    """Регистрирует все блюпринты приложения."""
    application.register_blueprint(chat_blueprint)
    application.register_blueprint(file_blueprint)
    application.register_blueprint(export_blueprint)
