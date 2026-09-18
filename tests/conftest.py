"""Общие фикстуры для тестов.

Изоляция обеспечивается через явный AppConfig с временными путями,
переданный в create_app. Никаких monkeypatch на глобальные объекты:
каждый тест получает собственное приложение со своим StreamManager,
своей БД и своим FakeOllamaService.

ВАЖНО: до первого импорта mini_llm_ui.config перезаписываем env,
чтобы тесты никогда не пошли на реальный Ollama-сервер.
"""

from __future__ import annotations

import os
import time
from collections.abc import Generator, Iterator
from dataclasses import replace
from pathlib import Path

# Жёстко перезаписываем env ДО первого импорта config. Даже если
# разработчик выставил OLLAMA_HOST в своём окружении — тесты не пойдут
# на реальный сервер.
os.environ['OLLAMA_MODEL'] = 'dummy'
os.environ['OLLAMA_HOST'] = 'http://127.0.0.1:1'

import pytest
from flask import Flask
from flask.testing import FlaskClient

from mini_llm_ui.app import create_app
from mini_llm_ui.config import AppConfig
from mini_llm_ui.config import config as default_config
from mini_llm_ui.services.stream_manager import StreamManager


class FakeOllamaService:
    """Заменяет OllamaService в тестах.

    Управляется через атрибуты:
      - tokens: последовательность чанков;
      - delay_seconds: пауза перед каждым чанком.

    stream_chat возвращает Generator пар (content, done):
      - в финальном чанке done=True — именно это завершает стрим
        в StreamManager, не дожидаясь закрытия HTTP-соединения;
      - во всех промежуточных чанках done=False.

    Возвращаемый генератор поддерживает close() — как того требует
    протокол SupportsStreamChat.
    """

    def __init__(
        self,
        tokens: list[str] | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self.tokens = tokens if tokens is not None else ['Hello', ' ', 'world']
        self.delay_seconds = delay_seconds
        self.received_calls: list[tuple[str, list[dict[str, str]]]] = []

    def stream_chat(
        self,
        model: str,
        messages: list[dict[str, str]],
    ) -> Generator[tuple[str, bool], None, None]:
        self.received_calls.append((model, messages))
        last_index = len(self.tokens) - 1
        for index, token in enumerate(self.tokens):
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
            # done=True только в финальном чанке — как у Ollama.
            yield token, index == last_index


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    """AppConfig с временными путями. Подменяет дефолтный config."""
    data_dir = tmp_path / 'data'
    uploads_dir = tmp_path / 'uploads'
    recovery_dir = data_dir / 'recovery'
    return replace(
        default_config,
        project_root=tmp_path,
        data_dir=data_dir,
        database_path=data_dir / 'chat.db',
        uploads_dir=uploads_dir,
        recovery_dir=recovery_dir,
        secret_key='test-secret-key-not-for-production',
    )


@pytest.fixture
def fake_ollama() -> FakeOllamaService:
    """Стандартный fake с быстрой генерацией (без задержек)."""
    return FakeOllamaService(
        tokens=['Hello', ', ', 'world', '!'],
        delay_seconds=0.0,
    )


@pytest.fixture
def app(
    app_config: AppConfig,
    fake_ollama: FakeOllamaService,
) -> Flask:
    """Flask-приложение с тестовым конфигом и быстрым fake Ollama.

    CSRF отключён: тестовый клиент не гоняет токен через каждый POST.
    """
    application = create_app(app_config=app_config)
    application.config['TESTING'] = True
    application.config['CSRF_ENABLED'] = False
    stream_manager: StreamManager = application.extensions['stream_manager']
    stream_manager._ollama = fake_ollama
    return application


@pytest.fixture
def client(app: Flask) -> Iterator[FlaskClient]:
    """Тестовый HTTP-клиент поверх быстрого app."""
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture
def slow_app(
    app_config: AppConfig,
    fake_ollama: FakeOllamaService,
) -> Flask:
    """Приложение с медленным fake-Ollama (0.3 с/токен).

    Задержка даёт окно, чтобы тест успел поймать середину стрима:
    проверить промежуточный poll, конфликт на второй POST, стоп
    до завершения.
    """
    fake_ollama.tokens = ['A', 'B', 'C', 'D']
    fake_ollama.delay_seconds = 0.3

    application = create_app(app_config=app_config)
    application.config['TESTING'] = True
    application.config['CSRF_ENABLED'] = False
    stream_manager: StreamManager = application.extensions['stream_manager']
    stream_manager._ollama = fake_ollama
    return application


@pytest.fixture
def slow_client(slow_app: Flask) -> Iterator[FlaskClient]:
    """Тестовый клиент поверх slow_app.

    yield обязателен: с return контекстный менеджер закрыл бы клиент
    до того, как тест начнёт его использовать.
    """
    with slow_app.test_client() as test_client:
        yield test_client


# ---------- Вспомогательные функции для тестов ----------------------------


def create_chat(client: FlaskClient) -> int:
    """Создаёт чат через POST и возвращает его id."""
    response = client.post('/chat/new', follow_redirects=False)
    assert response.status_code in (301, 302)
    location = response.headers['Location']
    return int(location.rstrip('/').rsplit('/', 1)[-1])


def wait_for_first_token(
    app: Flask,
    chat_id: int,
    timeout: float = 2.0,
) -> int | None:
    """Ждёт появления первого чанка в стриме чата.

    Использует публичный StreamManager.message_ids_with_content(),
    который фильтрует по непустому chunks (а не просто по факту
    резервации слота). Возвращает message_id или None при таймауте.
    """
    stream_manager: StreamManager = app.extensions['stream_manager']
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ids_with_content = stream_manager.message_ids_with_content(chat_id)
        if ids_with_content:
            return ids_with_content[0]
        time.sleep(0.02)
    return None
