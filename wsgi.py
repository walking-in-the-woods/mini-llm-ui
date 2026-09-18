"""WSGI-точка входа для gunicorn/uwsgi.

    gunicorn -w 1 -b 127.0.0.1:5000 wsgi:app

ВАЖНО: один воркер. StreamManager хранит активные стримы в памяти
процесса; второй воркер сломает polling и резервацию слотов.
"""
from __future__ import annotations

from mini_llm_ui.app import create_app

app = create_app()
