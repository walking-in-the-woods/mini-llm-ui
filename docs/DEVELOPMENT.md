# Разработка

Руководство для тех, кто меняет код mini-llm-ui. Установка для
пользователя — в `docs/INSTALL.md`.

## Быстрый старт

    git clone <repo> mini-llm-ui
    cd mini-llm-ui
    make install-dev
    make assets

Проверить, что всё работает:

    make test

Ожидается `30 passed` (или близкое число). Если что-то падает —
см. `docs/TROUBLESHOOTING.md`.

## Дерево задач

    make help          # список всех целей
    make install       # venv + runtime-зависимости
    make install-dev   # + ruff, mypy, pytest, coverage
    make assets        # скачать HTMX в mini_llm_ui/static/
    make run           # dev-сервер на 127.0.0.1:5000
    make test          # pytest
    make test-cov      # pytest с покрытием
    make lint          # ruff check
    make fmt           # ruff format
    make typecheck     # mypy strict
    make check         # lint + typecheck + test
    make clean         # удалить артефакты

## Стиль кода

- **Ruff** — линтер + форматер. Конфиг в `pyproject.toml`.
  Стиль: одинарные кавычки, длина строки 88, target Python 3.10.
- **Mypy strict** — вся типизация обязательна. `Any` допустим, но с
  явным обоснованием (комментарий или `cast`).
- **Docstring** — на русском, в стиле, близком к Google-style. Модули,
  классы, публичные функции — с докстрингами. Внутренние хелперы
  могут быть без, если имя говорит само за себя.
- **Длинные имена важнее коротких.** `message`, `attachment`,
  `stream_manager` — не `m`, `a`, `sm`.
- **Приватные члены — `_underscore`.** Публичный API минимизирован.

## Перед коммитом

    make check

Это три шага: lint → typecheck → test. Все три должны быть зелёными.
Если падает — присылать в issue не надо, поправьте локально.

Быстрая проверка только изменённого:

    .venv/bin/ruff check mini_llm_ui/routes/chat_routes.py
    .venv/bin/mypy mini_llm_ui/routes/chat_routes.py
    .venv/bin/pytest tests/test_smoke.py -v

## Соглашения о коммитах

Формат — Conventional Commits:

    <type>(<scope>): <короткое описание>

    <опционально: тело>

    <опционально: footer с Closes #123>

Типы:

- `feat` — новая функциональность (для пользователя);
- `fix` — исправление бага (для пользователя);
- `refactor` — изменения без влияния на поведение;
- `docs` — только документация;
- `test` — только тесты;
- `ci` — GitHub Actions, dependabot;
- `build` — pyproject.toml, Makefile, scripts/install.sh;
- `chore` — прочее (обновление .gitignore, перенос файлов).

Примеры:

    feat(routes): add /chat/<id>/export endpoint
    fix(stream_manager): preserve content on persist failure
    docs: describe soft-cancel limitations
    ci: add dependabot for pip and github-actions

## Тесты

Все тесты — в `tests/`. Фикстуры — в `tests/conftest.py`. Никаких
моков через `unittest.mock` — используется явная подстановка:

    stream_manager: StreamManager = app.extensions['stream_manager']
    stream_manager._ollama = fake_ollama

Это понятнее и надёжнее monkeypatch.

### Структура тестов

    tests/
    ├── conftest.py            # фикстуры app, client, slow_app, slow_client
    ├── test_host_check.py     # unit-тесты парсера Host (без Flask)
    ├── test_smoke.py          # создание чата, отправка, экспорт
    ├── test_streaming.py      # постепенный рост, стоп не теряет текст
    └── test_htmx_errors.py    # 409/400 + HX-Retarget, rollback при гонке

### Как добавить тест

1. Определите, к какой группе относится — маршрут, стриминг, ошибка,
   unit.
2. Добавьте в соответствующий файл.
3. Используйте фикстуру `client` для быстрых сценариев и
   `slow_client` — если нужно поймать промежуточное состояние
   стрима (0.3 с/токен).
4. Если нужен `FakeOllamaService` с особыми токенами — создайте
   свой инстанс и передайте в `slow_app`/`app`.

Пример — проверка, что ошибка генерации доходит до UI:

    def test_stream_error_is_visible(slow_app, slow_client):
        stream_manager: StreamManager = slow_app.extensions['stream_manager']
        def broken_stream(model, messages):
            raise RuntimeError('ollama dead')
        stream_manager._ollama.stream_chat = broken_stream

        chat_id = create_chat(slow_client)
        slow_client.post(f'/chat/{chat_id}/send', data={'content': 'go'})
        time.sleep(0.5)

        page = slow_client.get(f'/chat/{chat_id}')
        assert 'Ошибка генерации'.encode() in page.data

### Что не нужно тестировать

- Реальную Ollama. Все обращения — через `FakeOllamaService`.
- Реальную сеть (`requests`, `httpx`). Тестовый клиент Flask
  ходит напрямую в WSGI.
- Flask-внутренности (`request.host` без контекста). Если очень
  нужно — вызывайте чистые функции напрямую (`is_allowed_host`).

## Отладка

### Логи приложения

По умолчанию — `INFO` в stderr. Уровень меняется в
`mini_llm_ui/logging_config.py`.

Для подробных логов во время разработки:

    logging.basicConfig(level=logging.DEBUG)

временно в `create_app` (перед `configure_logging`) или
переменной окружения.

### Отладка в браузере

DevTools → Network. HTMX-запросы помечены заголовком
`HX-Request: true`. На вкладке Response видно тело ответа.

DevTools → Console. HTMX эмитит события `htmx:beforeSwap`,
`htmx:afterSwap`, `htmx:responseError` — можно вешать
`console.log` и смотреть, что происходит.

### Запуск с reload

`python app.py` использует `debug=False`. Для авто-перезагрузки при
правке кода временно поставьте `debug=True` в `app.py`:

    application.run(host=..., port=..., debug=True, threaded=True)

Или через `flask run`:

    FLASK_APP=mini_llm_ui.app:create_app flask run --debug

Правки в шаблонах Jinja подхватываются без перезапуска, если
`TEMPLATES_AUTO_RELOAD = True`. Flask включает это в debug-режиме.

### Отладка mypy

    .venv/bin/mypy --show-error-codes mini_llm_ui

Коды ошибок (`[return-value]`, `[assignment]`) гуглятся по
`docs.python.org/mypy/error_code_list.html`.

### Отладка ruff

    .venv/bin/ruff rule I001       # описание правила
    .venv/bin/ruff check --diff .  # показывает, что было бы исправлено

## Как выпустить релиз

1. Обновить `mini_llm_ui/__init__.py` → `__version__`.
2. Обновить `pyproject.toml` → `version`.
3. Добавить запись в `CHANGELOG.md` (см. ниже формат).
4. Закоммитить:

       git add -A
       git commit -m "release: v1.0.1"

5. Поставить тег:

       git tag -s v1.0.1 -m "Release v1.0.1"

6. Запушить с тегами:

       git push && git push --tags

GitHub Actions по тегу `v*.*.*` соберёт wheel + sdist и создаст
GitHub Release с автозаполнением из `CHANGELOG.md`.

## Формат CHANGELOG

Keep a Changelog, Semantic Versioning. Пример записи:

    ## [1.0.1] - 2026-10-15

    ### Fixed
    - Описание бага и что исправлено.

    ### Security
    - Описание уязвимости и фикса.

Категории: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`,
`Security`. Пустые категории не включать.

## См. также

- `docs/ARCHITECTURE.md` — как всё устроено, ключевые решения.
- `docs/SECURITY.md` — модель угроз.
- `CONTRIBUTING.md` — процесс PR.
- `CHANGELOG.md` — история версий.
