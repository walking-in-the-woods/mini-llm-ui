"""Точка входа для `python app.py`.

Вся логика — в пакете mini_llm_ui. Здесь только запуск dev-сервера.
Для продакшена — wsgi.py.
"""
from __future__ import annotations

from mini_llm_ui.app import run_dev_server


def main() -> None:
    run_dev_server()


if __name__ == '__main__':
    main()
