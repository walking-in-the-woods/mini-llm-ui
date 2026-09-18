"""Клиент Ollama: стриминг ответов и сборка промпта.

Класс OllamaService инкапсулирует ollama.Client, чтобы:
  - не создавать клиент на каждый запрос (keep-alive соединения);
  - позволить тестам подсунуть fake-реализацию без monkeypatch;
  - явно держать host в одном месте.

Стриминг отдаёт не только текст, но и признак завершения — поле
done из финального чанка ответа Ollama. Это позволяет StreamManager
не ждать закрытия HTTP-соединения, а завершать генерацию сразу,
как только модель закончила.
"""

from __future__ import annotations

import logging
from collections.abc import Generator, Sequence
from typing import Any, Final, Protocol

import ollama

from mini_llm_ui.config import AppConfig

_LOG = logging.getLogger(__name__)

_ATTACHMENT_HEADER_TEMPLATE: Final[str] = '--- Файл: {filename} ---'
_ATTACHMENT_SYSTEM_PREFIX: Final[str] = 'Прикреплённые файлы:\n\n'


class SupportsStreamChat(Protocol):
    """Протокол для подмены OllamaService в тестах.

    stream_chat возвращает Generator пар (content, done):
      - content: str — текстовый фрагмент ответа модели (может быть '');
      - done: bool — True в финальном чанке, когда генерация завершена.

    Контракт использует .close() для мягкой отмены, а у Iterator его
    нет — поэтому именно Generator.
    """

    def stream_chat(
        self,
        model: str,
        messages: list[dict[str, str]],
    ) -> Generator[tuple[str, bool], None, None]: ...


class OllamaService:
    """Обёртка над ollama.Client с стримингом.

    Клиент создаётся один раз в конструкторе — httpx внутри держит
    connection pool, что заметно ускоряет последовательные запросы
    на слабой машине.
    """

    def __init__(self, app_config: AppConfig) -> None:
        self._config = app_config
        self._client = ollama.Client(host=app_config.ollama_host)

    def stream_chat(
        self,
        model: str,
        messages: list[dict[str, str]],
    ) -> Generator[tuple[str, bool], None, None]:
        """Генератор пар (content, done) от ответа модели.

        Ollama стримит NDJSON: каждый чанк — отдельный JSON-объект,
        в финальном поле done=True. Мы прокидываем этот флаг наверх,
        чтобы StreamManager мог закрыть стрим немедленно.

        Возвращаемый объект поддерживает .close() — это контракт,
        на который опирается StreamManager для мягкой отмены.
        """
        response = self._client.chat(
            model=model,
            messages=messages,
            stream=True,
        )
        for chunk in response:
            content = _extract_chunk_content(chunk)
            done = _extract_chunk_done(chunk)
            yield content, done


def build_prompt_messages(
    history: Sequence[Any],
    attachments: Sequence[Any],
    max_history: int,
) -> list[dict[str, str]]:
    """Собирает список сообщений для Ollama.

    Правила:
      - вложения идут ОДИН раз system-сообщением в начале (а не в
        каждое user-сообщение — это критично для слабой машины);
      - история обрезается до последних max_history сообщений;
      - порядок ролей сохраняется как в БД.
    """
    prompt: list[dict[str, str]] = []

    if attachments:
        prompt.append(
            {
                'role': 'system',
                'content': _format_attachments(attachments),
            }
        )

    for message in history[-max_history:]:
        prompt.append(
            {
                'role': str(message['role']),
                'content': str(message['content']),
            }
        )

    return prompt


def _format_attachments(attachments: Sequence[Any]) -> str:
    """Склеивает вложения в единый system-блок.

    Формат:
        Прикреплённые файлы:

        --- Файл: a.md ---
        <содержимое>

        --- Файл: b.md ---
        <содержимое>
    """
    sections = [
        f'{_ATTACHMENT_HEADER_TEMPLATE.format(filename=attachment["filename"])}\n'
        f'{attachment["content"]}'
        for attachment in attachments
    ]
    return _ATTACHMENT_SYSTEM_PREFIX + '\n\n'.join(sections)


def _extract_chunk_content(chunk: Any) -> str:
    """Универсально достаёт .message.content из ответа ollama-python.

    SDK в разных версиях отдаёт dict или pydantic-модель. Приводим
    оба к строке — пустая строка, если поля нет.
    """
    if isinstance(chunk, dict):
        message = chunk.get('message')
        if isinstance(message, dict):
            return str(message.get('content', ''))
        return ''

    message_attr = getattr(chunk, 'message', None)
    if message_attr is None:
        return ''
    if isinstance(message_attr, dict):
        return str(message_attr.get('content', ''))
    return str(getattr(message_attr, 'content', '') or '')


def _extract_chunk_done(chunk: Any) -> bool:
    """Универсально достаёт флаг done из ответа ollama-python.

    Ollama присылает поле done=True в финальном чанке стрима.
    До появления этого флага генерация продолжается.
    """
    if isinstance(chunk, dict):
        return bool(chunk.get('done', False))
    return bool(getattr(chunk, 'done', False))
