"""Application factory.

create_app() собирает приложение из независимых частей:
  - конфиг (AppConfig) читается один раз при старте;
  - логирование настраивается однократно;
  - БД инициализируется и помечаются осиротевшие assistant-сообщения;
  - security-хуки (Host allow-list, CSRF) регистрируются;
  - сервисы (OllamaService, StreamManager) кладутся в app.extensions;
  - блюпринты регистрируются.

Никаких module-level сайд-эффектов — импорт app.py не создаёт БД,
не открывает соединений, не настраивает логирование.
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

from flask import Flask

from mini_llm_ui import __version__, constants
from mini_llm_ui.config import AppConfig
from mini_llm_ui.config import config as default_config
from mini_llm_ui.db import (
    close_request_connection,
    initialize_database,
    mark_orphaned_assistant_messages,
)
from mini_llm_ui.logging_config import configure_logging
from mini_llm_ui.routes import register_blueprints
from mini_llm_ui.security import (
    enforce_csrf_protection,
    enforce_host_allow_list,
    get_or_create_csrf_token,
)
from mini_llm_ui.services.ollama_service import OllamaService
from mini_llm_ui.services.stream_manager import StreamManager

_LOG = logging.getLogger(__name__)

_APP_CONFIG_KEY = 'APP_CONFIG'
_STREAM_MANAGER_EXTENSION_KEY = 'stream_manager'
_OLLAMA_SERVICE_EXTENSION_KEY = 'ollama_service'


def create_app(app_config: AppConfig | None = None) -> Flask:
    """Собирает и возвращает настроенное Flask-приложение.

    Аргумент app_config — для тестов: позволяет подсунуть конфиг с
    временными путями без monkeypatch на модуль config.
    """
    configure_logging()
    resolved_config = app_config or default_config

    application = Flask(
        __name__,
        template_folder='templates',
        static_folder='static',
    )
    application.config[_APP_CONFIG_KEY] = resolved_config
    application.config['MAX_CONTENT_LENGTH'] = resolved_config.max_request_size_bytes
    application.config['CSRF_ENABLED'] = resolved_config.csrf_enabled
    application.config['SECRET_KEY'] = _load_or_create_secret_key(resolved_config)

    _initialize_database(resolved_config)
    _register_services(application, resolved_config)
    _register_security_hooks(application)
    _register_lifecycle_hooks(application)
    _expose_template_globals(application)

    register_blueprints(application)

    _LOG.info(
        'mini-llm-ui v%s started (model=%s, host=%s)',
        __version__,
        resolved_config.ollama_model,
        resolved_config.ollama_host,
    )
    return application


# ---------- Инициализация компонентов -------------------------------------


def _initialize_database(app_config: AppConfig) -> None:
    """Создаёт БД и помечает осиротевшие сообщения после рестарта."""
    initialize_database(app_config)
    try:
        cleaned_count = mark_orphaned_assistant_messages(
            app_config,
            constants.ERROR_ORPHANED_ASSISTANT_MARKER,
        )
        if cleaned_count:
            _LOG.warning(
                'Marked %d orphaned assistant message(s) after restart',
                cleaned_count,
            )
    except Exception:
        _LOG.exception('Failed to cleanup orphaned assistant messages')


def _register_services(application: Flask, app_config: AppConfig) -> None:
    """Создаёт OllamaService и StreamManager, кладёт в app.extensions."""
    ollama_service = OllamaService(app_config)
    stream_manager = StreamManager(app_config, ollama_service)

    application.extensions[_OLLAMA_SERVICE_EXTENSION_KEY] = ollama_service
    application.extensions[_STREAM_MANAGER_EXTENSION_KEY] = stream_manager


def _register_security_hooks(application: Flask) -> None:
    """Регистрирует before_request-хуки Host allow-list и CSRF."""
    resolved_config: AppConfig = application.config[_APP_CONFIG_KEY]

    @application.before_request
    def _check_host() -> None:
        enforce_host_allow_list(resolved_config)

    @application.before_request
    def _check_csrf() -> None:
        enforce_csrf_protection(application.config['CSRF_ENABLED'])


def _register_lifecycle_hooks(application: Flask) -> None:
    """teardown: закрывает соединение БД в конце запроса."""
    application.teardown_appcontext(close_request_connection)


def _expose_template_globals(application: Flask) -> None:
    """Делает csrf_token() доступной во всех шаблонах Jinja."""
    application.jinja_env.globals['csrf_token'] = get_or_create_csrf_token


# ---------- SECRET_KEY ----------------------------------------------------


def _load_or_create_secret_key(app_config: AppConfig) -> str:
    """Возвращает SECRET_KEY с приоритетом: env > файл > новый сгенерированный.

    Файл создаётся через os.open(..., O_CREAT|O_EXCL, 0o600) — это
    исключает окно, когда файл существует с дефолтными правами.
    Запись завершается fsync: без него при power loss файл может
    остаться пустым.

    Если создать/прочитать не удалось — возвращаем непостоянный ключ.
    Сессии между перезапусками тогда теряются, но приложение работает.
    """
    if app_config.secret_key:
        return app_config.secret_key

    secret_path = app_config.data_dir / constants.SECRET_KEY_FILENAME
    try:
        secret_path.parent.mkdir(parents=True, exist_ok=True)

        existing = _read_secret_file(secret_path)
        if existing:
            return existing

        new_secret = secrets.token_hex(32)
        _write_secret_file(secret_path, new_secret)
        _LOG.info('Generated new SECRET_KEY at %s', secret_path)
        return new_secret
    except OSError:
        _LOG.exception(
            'Cannot read/write %s, using non-persistent key '
            '(sessions will not survive restart)',
            secret_path,
        )
        return secrets.token_hex(32)


def _read_secret_file(secret_path: Path) -> str | None:
    """Читает SECRET_KEY из файла, если он непустой."""
    if not secret_path.exists():
        return None
    content = secret_path.read_text(encoding='utf-8').strip()
    return content or None


def _write_secret_file(secret_path: Path, secret: str) -> None:
    """Пишет SECRET_KEY атомарно с правами 0600.

    Вторая попытка O_CREAT|O_EXCL обрабатывает редкую гонку: между
    exists() и open() файл мог создать параллельный процесс.
    """

    def _create_exclusive() -> int:
        return os.open(
            str(secret_path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )

    try:
        file_descriptor = _create_exclusive()
    except FileExistsError:
        # Гонка: другой процесс создал файл. Пробуем прочитать его.
        existing = _read_secret_file(secret_path)
        if existing:
            return
        # Файл пустой (обрыв прошлой записи) — пересоздаём.
        secret_path.unlink(missing_ok=True)
        file_descriptor = _create_exclusive()

    try:
        os.write(file_descriptor, secret.encode('utf-8'))
        os.fsync(file_descriptor)
    finally:
        os.close(file_descriptor)


# ---------- Точка входа dev-сервера ---------------------------------------


def run_dev_server() -> None:
    """Собирает приложение и запускает Flask dev-сервер на loopback.

    Печатает адрес, по которому открывать UI, один раз при старте.
    Только для локального использования; для продакшена — wsgi.py.
    """
    application = create_app()
    print(
        f'→ Откройте http://{constants.LISTEN_HOST}:{constants.LISTEN_PORT} в браузере',
        flush=True,
    )
    application.run(
        host=constants.LISTEN_HOST,
        port=constants.LISTEN_PORT,
        debug=False,
        threaded=True,
    )


if __name__ == '__main__':
    run_dev_server()
