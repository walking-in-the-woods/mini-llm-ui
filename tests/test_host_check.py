"""Unit-тесты для is_allowed_host.

Функция чистая — принимает host_header и allowed_hosts, возвращает bool.
Не требует Flask и не поднимает приложение.
"""

from __future__ import annotations

import pytest

from mini_llm_ui import constants
from mini_llm_ui.security import is_allowed_host

ALLOWED_HOSTS = constants.ALLOWED_HOSTS


@pytest.mark.parametrize(
    'host_header',
    [
        '127.0.0.1',
        '127.0.0.1:5000',
        'localhost',
        'localhost:5000',
        '[::1]',
        '[::1]:5000',
        'LOCALHOST:5000',  # регистронезависимость
    ],
)
def test_allowed_hosts(host_header: str) -> None:
    assert is_allowed_host(host_header, ALLOWED_HOSTS) is True


@pytest.mark.parametrize(
    'host_header',
    [
        '',  # fail-closed
        'evil.com',
        'evil.com:5000',
        '127.0.0.1.evil.com',  # суффиксное совпадение не проходит
        'localho.st',
        '192.168.1.1:5000',
        '::1',  # IPv6 без скобок невалиден по RFC 7230
        '[::2]:5000',
        '[2001:db8::1]:5000',
    ],
)
def test_rejected_hosts(host_header: str) -> None:
    assert is_allowed_host(host_header, ALLOWED_HOSTS) is False
