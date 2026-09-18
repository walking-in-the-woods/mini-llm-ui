"""Конфигурация приложения, читаемая из переменных окружения.

Все значения собираются в единственный frozen-инстанс AppConfig,
который создаётся на импорте модуля. Изменять его нельзя — это
осознанное решение: конфиг читается один раз при старте процесса,
и никакая часть приложения не должна менять его в рантайме.

В тестах пути переопределяются через dataclasses.replace и передачу
готового AppConfig в create_app (см. tests/conftest.py).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from mini_llm_ui import constants

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Снимок конфигурации процесса.

    Все поля — read-only. Для изменения в тестах используйте
    `dataclasses.replace(config, ...)` и подменяйте инстанс целиком.
    """

    # --- Ollama ---
    ollama_model: str
    ollama_host: str

    # --- Flask ---
    secret_key: str | None
    csrf_enabled: bool

    # --- Пути ---
    project_root: Path
    data_dir: Path
    database_path: Path
    uploads_dir: Path
    recovery_dir: Path

    # --- Ограничения ---
    max_file_size_bytes: int
    max_attachment_total_size_bytes: int
    max_request_size_bytes: int
    max_history_messages: int
    allowed_file_extensions: frozenset[str]

    # --- Безопасность ---
    allowed_hosts: frozenset[str] = field(
        default_factory=lambda: constants.ALLOWED_HOSTS
    )

    @classmethod
    def from_environment(cls) -> AppConfig:
        """Собирает конфиг из окружения с разумными дефолтами."""
        data_dir = _PROJECT_ROOT / constants.DATA_DIR_NAME
        return cls(
            ollama_model=os.getenv('OLLAMA_MODEL', 'llama3.2:3b'),
            ollama_host=os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434'),
            secret_key=os.getenv('SECRET_KEY'),
            csrf_enabled=True,
            project_root=_PROJECT_ROOT,
            data_dir=data_dir,
            database_path=data_dir / constants.DATABASE_FILENAME,
            uploads_dir=_PROJECT_ROOT / constants.UPLOADS_DIR_NAME,
            recovery_dir=data_dir / constants.RECOVERY_DIR_NAME,
            max_file_size_bytes=constants.MAX_FILE_SIZE_BYTES,
            max_attachment_total_size_bytes=(constants.MAX_ATTACHMENT_TOTAL_SIZE_BYTES),
            max_request_size_bytes=constants.MAX_REQUEST_SIZE_BYTES,
            max_history_messages=constants.MAX_HISTORY_MESSAGES,
            allowed_file_extensions=constants.ALLOWED_FILE_EXTENSIONS,
            allowed_hosts=constants.ALLOWED_HOSTS,
        )

    def ensure_directories(self) -> None:
        """Создаёт data/, uploads/, data/recovery/ при старте.

        Идемпотентно: повторный вызов ничего не ломает.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.recovery_dir.mkdir(parents=True, exist_ok=True)


# Единственный инстанс на процесс.
config: AppConfig = AppConfig.from_environment()
