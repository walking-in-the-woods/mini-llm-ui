# Troubleshooting

Сборник типовых проблем и их решений. Если вашего случая нет — заведите
issue с описанием шагов воспроизведения и выводом команд, которые
упомянуты ниже.

## Содержание

1. Терминал вылетает, система зависает, ОС убивает процессы
2. Порт 5000 уже занят
3. Ollama не отвечает на 127.0.0.1:11434
4. Модель не найдена
5. `make lint` / `make check` падает на ruff
6. `make typecheck` падает на mypy
7. `make test` падает
8. Приложение запускается, но UI пустой
9. Ошибки session / CSRF
10. HTMX не загружается, кнопки не работают
11. `.env` не подхватывается
12. Как посмотреть логи
13. Как остановить зависшие процессы

---

## 1. Терминал вылетает, система зависает, ОС убивает процессы

**Симптом.** Во время `pip install`, `mypy`, `pytest` или `make check`
терминал закрывается, окно пропадает, работа обрывается. ОС может
зависнуть на несколько секунд.

**Причина.** Почти всегда — OOM killer. На машине с 8 ГБ RAM и
запущенной Ollama (2–3 ГБ) плюс браузер (0.5–1 ГБ) свободной памяти
остаётся меньше 2 ГБ. `mypy --strict` пиково ест 0.5–1 ГБ.

### Как подтвердить

    free -h

Смотрите колонку `available`. Если меньше 2 ГБ при запуске `mypy` —
это оно.

Косвенно — через журнал ядра (требует sudo):

    sudo journalctl -k --since "15 minutes ago" | grep -i -E 'oom|killed'

Если видите строки вида `Out of memory: Killed process 12345 (python3)` —
подтверждено.

### Как лечить

1. **Остановить Ollama перед тяжёлыми операциями.**

       sudo systemctl stop ollama
       # или, если запущена вручную:
       pkill -f 'ollama serve'

2. **Запускать шаги по одному, а не через `make check`:**

       make lint        # ruff, легкий
       make typecheck   # mypy, тяжелый
       make test        # pytest, средний

3. **Отсоединять длительные процессы от терминала.** Даже если
   терминал упадёт — процесс продолжит работу, лог останется на диске:

       setsid -f bash -c 'cd "'"$PWD"'" && .venv/bin/mypy --no-incremental mini_llm_ui tests' > /tmp/mypy.log 2>&1

   Смотреть результат: `tail -f /tmp/mypy.log` (выход — `Ctrl+C`).

4. **Для mypy — без кеша в памяти.** В `Makefile` замените:

       typecheck:
           $(VENV)/bin/mypy --no-incremental mini_llm_ui tests

   Флаг `--no-incremental` снижает пиковое потребление.

5. **Уменьшить размер модели.** `llama3.2:3b` вместо `llama3.1:8b`.
   На N100 8B не влезает.

---

## 2. Порт 5000 уже занят

**Симптом.**

    OSError: [Errno 98] Address already in use

**Причина.** На 5000 кто-то уже слушает — прежний запуск `app.py`,
другой сервис, dev-сервер другого проекта.

### Как найти

    ss -tlnp | grep ':5000'
    # или
    lsof -i :5000

В выводе — PID и имя процесса.

### Как лечить

Остановить чужой процесс (если это ваш прежний запуск):

    pkill -f 'python app.py'

Или запустить приложение на другом порту:

    .venv/bin/python -c "from mini_llm_ui import constants; print(constants.LISTEN_PORT)"
    # затем в app.py или напрямую поменять константу LISTEN_PORT

Проще — временно через переменную, если используете `wsgi.py` с gunicorn:

    gunicorn -w 1 -b 127.0.0.1:5001 wsgi:app

---

## 3. Ollama не отвечает на 127.0.0.1:11434

**Симптом.** При отправке сообщения UI показывает
`⚠️ Ошибка генерации: ...`. В логе приложения — ошибки соединения.

### Как проверить

    curl -fsS http://127.0.0.1:11434/api/tags

Если соединение refused — Ollama не запущена. Запустить:

    ollama serve

Если уже запущена, но не отвечает — посмотреть, слушает ли порт:

    ss -tlnp | grep 11434

### Другая причина

`OLLAMA_HOST` указывает не туда. Проверить:

    echo "$OLLAMA_HOST"

Если пусто — используется дефолт `http://127.0.0.1:11434`. Если
значение другое — либо поправить, либо сбросить:

    unset OLLAMA_HOST

---

## 4. Модель не найдена

**Симптом.** UI показывает ошибку вида `model 'llama3.2:3b' not found`.

### Как проверить

    ollama list

В списке должна быть модель, совпадающая с `OLLAMA_MODEL`.

### Как лечить

Скачать нужную:

    ollama pull llama3.2:3b

Или изменить `OLLAMA_MODEL` на уже имеющуюся:

    export OLLAMA_MODEL=qwen2.5-coder:3b
    make run

Убедиться, что `config.py` не переопределяет значение:

    grep -n OLLAMA_MODEL mini_llm_ui/config.py

---

## 5. `make lint` / `make check` падает на ruff

**Симптом.** Ruff находит N ошибок в коде или тестах.

### Если ошибки в вашем коде

Прогнать автофикс:

    .venv/bin/ruff check mini_llm_ui tests --fix
    .venv/bin/ruff format mini_llm_ui tests

Проверить, что осталось:

    .venv/bin/ruff check mini_llm_ui tests

### Если правило не подходит проекту

Добавить в `pyproject.toml`:

    [tool.ruff.lint]
    ignore = ["КОД_ПРАВИЛА"]

или для конкретного файла:

    [tool.ruff.lint.per-file-ignores]
    "путь/к/файлу.py" = ["КОД_ПРАВИЛА"]

### Частые ложные срабатывания

- `S105` (`SECRET_KEY` в имени) — добавить в per-file-ignores.
- `S106` (hardcoded password) — то же.
- `RUF001/002/003` (ambiguous unicode) — для русскоязычных docstring
  добавить в глобальный `ignore`.
- `I001` (порядок импортов) — автофикс.

---

## 6. `make typecheck` падает на mypy

**Симптом.** Mypy показывает список ошибок с кодами.

### Частые случаи

- `Cannot find implementation or library stub for module named "X"` —
  нет type stubs. Решение: добавить в `pyproject.toml`:

      [[tool.mypy.overrides]]
      module = "X.*"
      ignore_missing_imports = true

- `Returning Any from function declared to return "X"` — явно
  типизировать возврат: обернуть в `str(...)`, `int(...)`,
  `cast(str, ...)`.

- `Item "None" of "Optional[X]" has no attribute "Y"` — проверка
  на `None` перед использованием.

### Если mypy тормозит или падает по памяти

    .venv/bin/mypy --no-incremental mini_llm_ui tests

Без `--no-incremental` mypy пишет кеш в `.mypy_cache/`, что быстрее,
но пиково ест больше памяти.

---

## 7. `make test` падает

**Симптом.** Pytest показывает `N failed`.

### Диагностика одного теста

    .venv/bin/python -m pytest tests/test_smoke.py -v
    .venv/bin/python -m pytest tests/test_smoke.py::test_send_message_and_receive_streamed_reply -vv

Флаг `-vv` покажет полный traceback и ассерты.

### Частые причины

- **Тест зависит от задержки Ollama.** `FakeOllamaService` в
  `tests/conftest.py` управляется через `tokens` и `delay_seconds`.
  Если тест ждёт результата через `time.sleep(0.2)`, а fake быстрый —
  race. Заменить на ожидание через `wait_for_first_token`.

- **Тест не изолирован.** Все фикстуры создают временные директории
  через `tmp_path`, состояние `StreamManager` изолировано. Если
  добавлен тест, обращающийся к реальной БД — переписать под фикстуру
  `app_config`.

- **Стрим не завершился к моменту проверки.** Фоновый поток работает
  асинхронно. Для проверки «после завершения» — увеличить паузу или
  дождаться через `active_message_ids` и `wait_for_first_token`.

### Если упал один тест, а не все

    .venv/bin/python -m pytest -x -v

Флаг `-x` останавливает на первой ошибке, `-v` показывает имена.

---

## 8. Приложение запускается, но UI пустой

**Симптом.** Браузер открывает http://127.0.0.1:5000, но страница
пустая или без стилей.

### Стили и HTMX не загружаются

HTMX не скачан. Проверить:

    ls -la mini_llm_ui/static/htmx.min.js

Если файла нет:

    ./scripts/fetch_assets.sh

При этом `app.css` должен быть на месте всегда (он в репозитории).

### Браузер показывает старую версию

Кеш браузера. Открыть DevTools (F12) → вкладка Network → поставить
галочку «Disable cache» → перезагрузить (`Ctrl+Shift+R`).

### Пустой ответ от сервера

Открыть DevTools → вкладка Network → посмотреть, какой код приходит
на запрос `/`. Если 500 — смотреть логи приложения (см. раздел 12).

---

## 9. Ошибки session / CSRF

**Симптом.** После отправки формы — `400 Bad Request: CSRF token
invalid`.

### Причина

- Сессия сбросилась (перезапуск приложения + `SECRET_KEY` менялся).
- Изменился IP или Host, а куки привязаны к домену.

### Как лечить

Перезагрузить страницу — токен сгенерируется заново. Если не помогает —
очистить куки для `127.0.0.1:5000` в браузере.

В `data/secret_key` лежит ключ подписи. Убедиться, что файл существует
и права 0600:

    ls -la data/secret_key

Если файл удалён, при следующем старте сгенерируется новый — все
сессии сбросятся.

---

## 10. HTMX не загружается, кнопки не работают

**Симптом.** В консоли браузера — `htmx is not defined`. Ни одна
HTMX-кнопка не работает.

### Проверить

Открыть в браузере напрямую:

    http://127.0.0.1:5000/static/htmx.min.js

Если 404 — файл не скачан (см. раздел 8). Если отдаётся содержимое —
проверить `<script src="...">` в `mini_llm_ui/templates/base.html`.

### Порядок подключения

В `base.html` должно быть:

    <script src="{{ url_for('static', filename='htmx.min.js') }}" defer></script>

`defer` обязателен — иначе HTMX может грузиться до DOM.

---

## 11. `.env` не подхватывается

**Симптом.** Переменные в `.env` есть, а приложение их не видит.

**Причина.** `.env` — это просто шаблон. Flask не читает его
автоматически. Автозагрузка `.env` требует `python-dotenv` и явного
вызова `load_dotenv()`.

### Как лечить

Экспортировать переменные вручную:

    export OLLAMA_MODEL=llama3.2:3b
    export SECRET_KEY=$(openssl rand -hex 32)
    make run

Или использовать shell-обёртку:

    set -a
    source .env
    set +a
    make run

Или поставить `python-dotenv` и добавить в `app.py`:

    from dotenv import load_dotenv
    load_dotenv()

В текущей версии этого нет — сделано сознательно, чтобы не тянуть
ещё одну зависимость.

---

## 12. Как посмотреть логи

### Логи приложения

Пишутся в stdout процесса `app.py` или `wsgi`. Если запускали через
`setsid` и лог перенаправлен в файл:

    tail -f /tmp/app.log

Если запускали через systemd — в journal:

    journalctl --user -u mini-llm-ui -f
    # или, если юнит системный:
    sudo journalctl -u mini-llm-ui -f

### Логи Ollama

    journalctl -u ollama -f
    # или, если запущена в терминале — там же, где запускали

### Логи тестов

Pytest при падении показывает captured output прямо в консоли.
С флагом `-s` не перехватывает:

    .venv/bin/python -m pytest -s

### Логи ruff / mypy

Ничего не пишут в файлы — только в stdout. Перенаправляйте сами:

    .venv/bin/mypy mini_llm_ui tests > /tmp/mypy.log 2>&1

---

## 13. Как остановить зависшие процессы

### Найти все свои процессы проекта

    pgrep -fa 'mini_llm_ui\|app\.py\|ollama serve'

### Остановить приложение

    pkill -f 'python.*app\.py'
    # или по PID из pgrep:
    kill <PID>

### Остановить Ollama

    pkill -f 'ollama serve'
    # или, если systemd-сервис:
    sudo systemctl stop ollama

### Остановить gunicorn

    pkill -f 'gunicorn.*mini_llm_ui'

### Все зависшие тесты

    pkill -f 'pytest'
    pkill -f 'mypy'

**Не используйте `pkill -9`** — обычный SIGTERM даёт процессу время
корректно закрыть SQLite-соединения. `-9` может оставить
`chat.db-wal` в несогласованном состоянии (обычно безопасно, SQLite
восстанавливается, но лучше избегать).

### Проверить, что ничего не осталось

    pgrep -fa 'mini_llm_ui\|app\.py\|pytest\|mypy\|ollama serve' || echo 'чисто'
