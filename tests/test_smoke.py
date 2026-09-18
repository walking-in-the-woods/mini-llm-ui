"""Smoke-тесты: создание чата, отправка, стриминг, экспорт."""

from __future__ import annotations

import re
import time

from flask.testing import FlaskClient
from tests.conftest import create_chat


def test_index_returns_redirect_or_empty_state(client: FlaskClient) -> None:
    response = client.get('/')
    assert response.status_code in (200, 302)


def test_create_chat_redirects_to_it(client: FlaskClient) -> None:
    chat_id = create_chat(client)
    assert chat_id > 0


def test_send_message_and_receive_streamed_reply(client: FlaskClient) -> None:
    chat_id = create_chat(client)
    response = client.post(
        f'/chat/{chat_id}/send',
        data={'content': 'test message'},
    )
    assert response.status_code == 200
    assert b'test message' in response.data

    time.sleep(0.2)  # ждём завершения фонового потока

    page = client.get(f'/chat/{chat_id}')
    assert page.status_code == 200
    assert b'Hello' in page.data


def test_empty_message_returns_204(client: FlaskClient) -> None:
    chat_id = create_chat(client)
    response = client.post(f'/chat/{chat_id}/send', data={'content': '   '})
    assert response.status_code == 204


def test_export_message_as_markdown(client: FlaskClient) -> None:
    chat_id = create_chat(client)
    client.post(f'/chat/{chat_id}/send', data={'content': 'export me'})
    time.sleep(0.2)

    page = client.get(f'/chat/{chat_id}')
    match = re.search(rb'id="message-(\d+)"', page.data)
    assert match is not None
    message_id = int(match.group(1))

    response = client.get(f'/chat/{chat_id}/message/{message_id}/export')
    assert response.status_code == 200
    assert response.headers['Content-Type'].startswith('text/markdown')
    assert b'export me' in response.data


def test_delete_chat_removes_it(client: FlaskClient) -> None:
    chat_id = create_chat(client)
    client.post(f'/chat/{chat_id}/delete')
    page = client.get('/')
    # После удаления единственного чата index отрисует пустое состояние.
    assert page.status_code == 200
