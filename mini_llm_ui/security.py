"""Защитные механизмы: Host allow-list и CSRF.

Модуль сознательно не зависит от глобального Flask-приложения: все
функции принимают явные аргументы. Это позволяет тестировать их
изолированно (см. tests/test_host_check.py).
"""

from __future__ import annotations

import logging
import secrets
from typing import Final

from flask import Request, Response, abort, request, session

from mini_llm_ui.config import AppConfig

_LOG = logging.getLogger(__name__)

_CSRF_SESSION_KEY: Final[str] = '_csrf'
_CSRF_FORM_FIELD: Final[str] = '_csrf'
_CSRF_HEADER_NAME: Final[str] = 'X-CSRFToken'

_SAFE_METHODS: Final[frozenset[str]] = frozenset({'GET', 'HEAD', 'OPTIONS'})


# ---------- Host allow-list (анти-DNS-rebinding) --------------------------


def is_allowed_host(host_header: str, allowed_hosts: frozenset[str]) -> bool:
    """Проверяет Host-заголовок против allow-list.

    Fail-closed: пустая строка отклоняется.

    Поддерживает IPv4, hostname и IPv6 в скобках, с портом или без:
      '127.0.0.1', '127.0.0.1:5000', 'localhost', '[::1]', '[::1]:5000'.

    IPv6 без скобок ('::1') невалиден по RFC 7230 и отклоняется:
    парсер не пытается угадать, что подразумевал клиент.
    """
    if not host_header:
        return False

    host = host_header.strip()
    if host.startswith('['):
        closing_bracket = host.find(']')
        host_only = host[: closing_bracket + 1] if closing_bracket != -1 else host
    elif ':' in host:
        host_only = host.rsplit(':', 1)[0]
    else:
        host_only = host

    candidates = {host_only.lower(), host_only.strip('[]').lower()}
    normalised_allowed = {item.lower().strip('[]') for item in allowed_hosts}
    return bool(candidates & normalised_allowed)


def enforce_host_allow_list(app_config: AppConfig) -> None:
    """before_request-хук: отклоняет запросы с недопустимым Host.

    Защищает от DNS rebinding: злоумышленник со своим доменом,
    указывающим на 127.0.0.1, получит 400, потому что его Host
    не входит в allow-list.
    """
    if not is_allowed_host(request.host or '', app_config.allowed_hosts):
        _LOG.warning('Rejected request with Host=%r', request.host)
        abort(400, 'Invalid Host header')


# ---------- CSRF ----------------------------------------------------------


def get_or_create_csrf_token() -> str:
    """Возвращает CSRF-токен текущей сессии, создавая его при первом вызове.

    Экспортируется в Jinja как глобальная функция csrf_token(), чтобы
    шаблоны могли вставлять `<input type="hidden" name="_csrf" ...>`.
    """
    stored = session.get(_CSRF_SESSION_KEY)
    if isinstance(stored, str) and stored:
        return stored

    token = secrets.token_urlsafe(32)
    session[_CSRF_SESSION_KEY] = token
    return token


def _extract_submitted_token(http_request: Request) -> str | None:
    """Достаёт токен из формы или заголовка.

    Форма — для обычных POST (form submit). Заголовок — для HTMX и
    fetch-запросов, где нет удобного способа вставить hidden input.
    """
    if http_request.method in _SAFE_METHODS:
        return None

    form_token = http_request.form.get(_CSRF_FORM_FIELD)
    if isinstance(form_token, str) and form_token:
        return form_token

    header_token = http_request.headers.get(_CSRF_HEADER_NAME)
    if isinstance(header_token, str) and header_token:
        return header_token

    return None


def enforce_csrf_protection(csrf_enabled: bool) -> None:
    """before_request-хук: проверяет CSRF-токен для небезопасных методов.

    В тестах CSRF отключается через app.config['CSRF_ENABLED'] = False,
    чтобы не гонять токен через каждый POST-запрос.
    """
    if not csrf_enabled:
        return
    if request.method in _SAFE_METHODS:
        return

    submitted = _extract_submitted_token(request)
    expected = session.get(_CSRF_SESSION_KEY)

    if not submitted or not isinstance(expected, str) or not expected:
        _LOG.warning(
            'CSRF check failed (missing token) for %s %s',
            request.method,
            request.path,
        )
        abort(400, 'CSRF token invalid')

    if not secrets.compare_digest(submitted, expected):
        _LOG.warning(
            'CSRF check failed (mismatch) for %s %s',
            request.method,
            request.path,
        )
        abort(400, 'CSRF token invalid')


# ---------- Ответы об ошибках для HTMX ------------------------------------


def make_htmx_error_response(
    message: str,
    *,
    status: int,
    target_selector: str,
) -> Response:
    """Формирует HTML-ответ с ошибкой для HTMX.

    HTMX по умолчанию не свапает контент при 4xx, поэтому клиентский
    beforeSwap-override (в base.html) разрешает swap для 400/409.
    Само тело ответа — короткий span, который вставляется в target.

    Возвращаем именно 4xx (а не 200), чтобы:
      - event.detail.xhr.status на клиенте был реальным кодом;
      - обработчики не путали успех с ошибкой, даже если htmx
        пересчитает successful в своей внутренней логике.
    """
    response = Response(
        f'<span class="error">{message}</span>',
        status=status,
        mimetype='text/html; charset=utf-8',
    )
    response.headers['HX-Retarget'] = target_selector
    response.headers['HX-Reswap'] = 'innerHTML'
    return response
