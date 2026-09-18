"""Запуск через `python -m mini_llm_ui`.

Эквивалентен `python app.py` в корне проекта.
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
