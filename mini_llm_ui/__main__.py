"""Запуск через `python -m mini_llm_ui`.

Эквивалентен `python app.py` в корне проекта.
"""

from __future__ import annotations

from mini_llm_ui.app import run_dev_server


def main() -> None:
    run_dev_server()


if __name__ == '__main__':
    main()
