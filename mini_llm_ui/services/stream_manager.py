"""Управление активными стримами ответов от Ollama.

StreamManager — stateful-компонент. Один инстанс на процесс,
создаётся в create_app и живёт в app.extensions['stream_manager'].

Конкурентная модель:
  - все операции чтения/записи self._streams идут под self._lock;
  - длинные операции (Ollama, БД, файловая система) — вне lock;
  - per-message cancel_event для мягкой остановки;
  - резервация слота — атомарная (try_reserve), не check-then-act.

Завершение стрима:
  - основной сигнал — флаг done=True в финальном чанке Ollama.
    Как только он получен, _worker выходит из цикла и вызывает
    _finalize_state. Не ждём EOF/close от httpx — на медленных
    соединениях это могло занимать секунды, и всё это время UI
    оставался заблокированным.
  - мягкая отмена (cancel_event) — тоже выходит из цикла и
    завершает стрим с маркером.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from mini_llm_ui import constants
from mini_llm_ui.config import AppConfig
from mini_llm_ui.db import open_standalone_connection
from mini_llm_ui.services.markdown_service import render_markdown
from mini_llm_ui.services.ollama_service import SupportsStreamChat

_LOG = logging.getLogger(__name__)


@dataclass
class _StreamState:
    """Внутреннее состояние одного стрима.

    Мутируется только под StreamManager._lock. Наружу отдаётся
    иммутабельный снапшот (StreamSnapshot).
    """

    chat_id: int
    chunks: list[str] = field(default_factory=list)
    done: bool = False
    cancelled: bool = False
    cancel_requested: bool = False
    error: str | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    persisted: bool = False

    def joined_content(self) -> str:
        """Склеивает чанки. Вызывается вне lock — чанки уже собраны."""
        return ''.join(self.chunks)


@dataclass(frozen=True)
class StreamSnapshot:
    """Иммутабельный снимок состояния для UI."""

    chat_id: int
    content: str
    done: bool
    cancelled: bool
    cancel_requested: bool
    error: str | None
    persisted: bool


class StreamManager:
    """Управляет жизненным циклом стримов ответов Ollama."""

    _CLEANUP_DELAY_SECONDS: Final[float] = constants.STREAM_CLEANUP_DELAY_SECONDS
    _CLEANUP_DELAY_AFTER_DB_FAIL_SECONDS: Final[float] = (
        constants.STREAM_CLEANUP_DELAY_AFTER_DB_FAIL_SECONDS
    )

    def __init__(
        self,
        app_config: AppConfig,
        ollama_service: SupportsStreamChat,
    ) -> None:
        self._config = app_config
        self._ollama = ollama_service
        self._streams: dict[int, _StreamState] = {}
        self._lock = threading.Lock()

    # ---------- Резервация ------------------------------------------------

    def try_reserve(self, chat_id: int, message_id: int) -> bool:
        """Атомарно резервирует слот стрима для чата.

        Возвращает False, если в чате уже идёт активная генерация.
        Вызывается ДО создания placeholder-ассистента в БД, чтобы
        не оставлять мусор при отказе.
        """
        with self._lock:
            if self._has_active_locked(chat_id):
                return False
            self._streams[message_id] = _StreamState(chat_id=chat_id)
            return True

    def release_reservation(self, message_id: int) -> None:
        """Откатывает try_reserve, если запустить генерацию не удалось."""
        with self._lock:
            self._streams.pop(message_id, None)

    # ---------- Чтение состояния ------------------------------------------

    def has_active_stream(self, chat_id: int) -> bool:
        """Есть ли в чате незавершённый стрим."""
        with self._lock:
            return self._has_active_locked(chat_id)

    def get_snapshot(self, message_id: int) -> StreamSnapshot | None:
        """Иммутабельный снимок состояния стрима или None."""
        with self._lock:
            state = self._streams.get(message_id)
            if state is None:
                return None
            return StreamSnapshot(
                chat_id=state.chat_id,
                content=state.joined_content(),
                done=state.done,
                cancelled=state.cancelled,
                cancel_requested=state.cancel_requested,
                error=state.error,
                persisted=state.persisted,
            )

    def active_message_ids(self, chat_id: int) -> list[int]:
        """Список message_id с активными (не done) стримами в чате.

        Публичный метод для тестов и диагностики: не требует доступа
        к приватному _streams. Возвращает отсортированный список.
        """
        with self._lock:
            return sorted(
                message_id
                for message_id, state in self._streams.items()
                if state.chat_id == chat_id and not state.done
            )

    def message_ids_with_content(self, chat_id: int) -> list[int]:
        """ID стримов в чате, у которых уже есть хотя бы один чанк.

        Отличие от active_message_ids: тот возвращает слот сразу после
        резервации, когда чанков ещё нет. Этот ждёт первого токена.
        Используется тестами, которым нужно поймать середину стрима.
        """
        with self._lock:
            return sorted(
                message_id
                for message_id, state in self._streams.items()
                if state.chat_id == chat_id and state.chunks
            )

    # ---------- Управление -------------------------------------------------

    def start(
        self,
        message_id: int,
        model: str,
        prompt_messages: list[dict[str, str]],
    ) -> None:
        """Запускает генерацию в фоновом потоке.

        Требует предварительного try_reserve. Если слот не зарезервирован,
        это программная ошибка вызывающего кода.
        """
        with self._lock:
            if message_id not in self._streams:
                raise RuntimeError(f'stream slot {message_id} is not reserved')

        worker = threading.Thread(
            target=self._run_worker,
            args=(message_id, model, prompt_messages),
            daemon=True,
            name=f'ollama-stream-{message_id}',
        )
        worker.start()

    def cancel(self, message_id: int) -> bool:
        """Запрашивает мягкую остановку.

        Возвращает True, если слот существует и ещё не завершён.
        cancel_requested взводится немедленно, чтобы UI сменил статус
        на «останавливается…» уже на следующем poll-тике.
        """
        with self._lock:
            state = self._streams.get(message_id)
            if state is None or state.done:
                return False
            state.cancel_requested = True
            state.cancel_event.set()
            return True

    # ---------- Внутренняя реализация -------------------------------------

    def _has_active_locked(self, chat_id: int) -> bool:
        """Проверка активности без захвата lock. Вызывать под self._lock."""
        return any(
            state.chat_id == chat_id and not state.done
            for state in self._streams.values()
        )

    def _run_worker(
        self,
        message_id: int,
        model: str,
        prompt_messages: list[dict[str, str]],
    ) -> None:
        """Фоновый поток: читает поток Ollama и финализирует сообщение.

        Цикл завершается при наступлении любого из трёх событий:
          1. Ollama прислала финальный чанк с done=True — нормальный
             конец генерации. Именно этот случай — основной, и он
             позволяет не ждать закрытия HTTP-соединения, чтобы
             не держать UI в заблокированном состоянии лишние секунды.
          2. Пользователь нажал «стоп» — cancel_event взведён.
          3. Слот исчез из self._streams (теоретически возможно,
             если менеджер заменён или очищен).
        """
        error: str | None = None
        cancelled = False
        generator = self._ollama.stream_chat(model, prompt_messages)

        try:
            for content, done in generator:
                with self._lock:
                    state = self._streams.get(message_id)
                    if state is None:
                        cancelled = True
                        break
                    if state.cancel_event.is_set():
                        cancelled = True
                        break
                    if content:
                        state.chunks.append(content)
                    if done:
                        # Ollama закончила генерацию. Выходим сразу,
                        # не ожидая EOF от httpx. Это разблокирует
                        # composer у пользователя на следующем же
                        # poll-тике.
                        break
        except Exception as stream_error:
            error = str(stream_error)
            _LOG.exception('Ollama stream failed (message_id=%s)', message_id)
        finally:
            # Закрытие генератора освобождает соединение httpx.
            # Ошибки закрытия не должны перекрывать основной результат.
            with contextlib.suppress(Exception):
                generator.close()

        final_content = self._finalize_state(message_id, cancelled, error)
        persisted = self._persist(message_id, final_content)
        self._update_persisted_flag(message_id, persisted)

        if not persisted:
            self._write_recovery_file(message_id, final_content)

        delay = (
            self._CLEANUP_DELAY_SECONDS
            if persisted
            else self._CLEANUP_DELAY_AFTER_DB_FAIL_SECONDS
        )
        timer = threading.Timer(delay, self._cleanup, args=(message_id,))
        timer.daemon = True
        timer.start()

    def _finalize_state(
        self,
        message_id: int,
        cancelled: bool,
        error: str | None,
    ) -> str:
        """Проставляет финальные флаги и добавляет маркеры в чанки."""
        with self._lock:
            state = self._streams.get(message_id)
            if state is None:
                return ''

            current_content = state.joined_content()

            if cancelled and not current_content.endswith(
                constants.STREAM_CANCEL_MARKER
            ):
                if current_content:
                    state.chunks.append(constants.STREAM_CANCEL_MARKER)
                else:
                    state.chunks.append(constants.STREAM_CANCEL_MARKER.strip())
            elif not current_content and error:
                state.chunks.append(
                    constants.ERROR_STREAM_FAILURE_TEMPLATE.format(error=error)
                )

            state.done = True
            state.cancelled = cancelled
            state.error = error
            return state.joined_content()

    def _persist(self, message_id: int, content: str) -> bool:
        """Записывает финальный контент в БД. Возвращает True при успехе."""
        try:
            connection = open_standalone_connection(self._config)
            try:
                html_content = render_markdown(content)
                connection.execute(
                    'UPDATE messages SET content = ?, html_content = ? WHERE id = ?',
                    (content, html_content, message_id),
                )
                connection.commit()
            finally:
                connection.close()
        except Exception:
            _LOG.exception(
                'Failed to persist streamed message (message_id=%s)',
                message_id,
            )
            return False

        # Успешный персист — старый recovery-файл больше не нужен.
        self._remove_recovery_file(message_id)
        return True

    def _update_persisted_flag(self, message_id: int, persisted: bool) -> None:
        with self._lock:
            state = self._streams.get(message_id)
            if state is not None:
                state.persisted = persisted

    # ---------- Recovery-файлы --------------------------------------------

    def _recovery_path(self, message_id: int) -> Path:
        filename = constants.RECOVERY_FILE_TEMPLATE.format(message_id=message_id)
        return self._config.recovery_dir / filename

    def _write_recovery_file(self, message_id: int, content: str) -> None:
        """Сохраняет контент в data/recovery/msg_<id>.md атомарно.

        Атомарность через tmp + os.replace: если процесс упадёт
        посередине, останется либо старый файл, либо новый, но не
        обрезанный.
        """
        try:
            self._config.recovery_dir.mkdir(parents=True, exist_ok=True)
            final_path = self._recovery_path(message_id)
            temporary_path = final_path.with_name(final_path.name + '.tmp')
            temporary_path.write_text(content, encoding='utf-8')
            os.replace(temporary_path, final_path)
            _LOG.warning(
                'Persisted recovery file for message_id=%s at %s',
                message_id,
                final_path,
            )
        except Exception:
            _LOG.exception(
                'Failed to write recovery file for message_id=%s',
                message_id,
            )

    def _remove_recovery_file(self, message_id: int) -> None:
        try:
            self._recovery_path(message_id).unlink(missing_ok=True)
        except Exception:
            _LOG.exception(
                'Failed to remove recovery file for message_id=%s',
                message_id,
            )

    # ---------- Очистка ---------------------------------------------------

    def _cleanup(self, message_id: int) -> None:
        """Удаляет завершённый стрим из памяти.

        Вызывается через threading.Timer. После этого get_snapshot
        вернёт None, и UI будет опираться только на БД.
        """
        with self._lock:
            self._streams.pop(message_id, None)
