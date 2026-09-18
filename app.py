"""Точка входа для `python app.py`.

Вся логика — в пакете mini_llm_ui. Здесь только сборка приложения
и запуск dev-сервера Flask. Для продакшена — wsgi.py.
"""
from __future__ import annotations

from mini_llm_ui import constants
from mini_llm_ui.app import create_app


def main() -> None:
    application = create_app()
    application.run(
        host=constants.LISTEN_HOST,
        port=constants.LISTEN_PORT,
        debug=False,
        threaded=True,
    )


if __name__ == '__main__':
    main()
