"""Рендеринг Markdown в HTML.

escape=True экранирует сырой HTML из ответов модели и загруженных
файлов. Без этого prompt injection в прикреплённом файле мог бы
выдать `<script>` и выполнить его в браузере пользователя в контексте
127.0.0.1.
"""

from __future__ import annotations

from typing import Final, cast

import mistune

_MARKDOWN_RENDERER: Final = mistune.create_markdown(
    escape=True,
    plugins=['strikethrough', 'table', 'url', 'task_lists'],
)


def render_markdown(text: str) -> str:
    """Возвращает HTML-представление Markdown-текста.

    Пустой вход → пустая строка (без обёрток-параграфов).
    """
    if not text:
        return ''
    return cast(str, _MARKDOWN_RENDERER(text))
