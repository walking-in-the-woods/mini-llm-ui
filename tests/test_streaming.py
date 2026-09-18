"""Регрессия: стриминг отдаёт контент постепенно, стоп не теряет текст."""

from __future__ import annotations

import time

from flask import Flask
from flask.testing import FlaskClient

from tests.conftest import create_chat, wait_for_first_token


def test_streaming_yields_incremental_content(
    slow_app: Flask,
    slow_client: FlaskClient,
) -> None:
    chat_id = create_chat(slow_client)
    response = slow_client.post(
        f'/chat/{chat_id}/send',
        data={'content': 'go'},
    )
    assert response.status_code == 200

    message_id = wait_for_first_token(slow_app, chat_id)
    assert message_id is not None, 'stream did not start'

    # Сразу после первого токена — poll должен вернуть непустой контент.
    first_poll = slow_client.get(f'/chat/{chat_id}/message/{message_id}/poll')
    assert first_poll.status_code == 200
    assert b'A' in first_poll.data
    # И это ещё не всё сообщение — стрим продолжается.
    assert b'ABCD' not in first_poll.data

    # Дожидаемся завершения.
    time.sleep(1.5)
    final = slow_client.get(f'/chat/{chat_id}/message/{message_id}/poll')
    assert b'ABCD' in final.data


def test_stop_preserves_visible_content(
    slow_app: Flask,
    slow_client: FlaskClient,
) -> None:
    chat_id = create_chat(slow_client)
    slow_client.post(f'/chat/{chat_id}/send', data={'content': 'go'})

    message_id = wait_for_first_token(slow_app, chat_id)
    assert message_id is not None

    stop_response = slow_client.post(f'/chat/{chat_id}/message/{message_id}/stop')
    assert stop_response.status_code == 200
    # Контент, который уже был виден, не пропал.
    assert b'A' in stop_response.data
    # Статус сменился на «останавливается…».
    assert 'останавливается'.encode() in stop_response.data
