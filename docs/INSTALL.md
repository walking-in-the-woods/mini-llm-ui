# Установка mini-llm-ui

Документ описывает установку и первый запуск приложения на локальной
машине. Рассчитан на пользователя, который уже знаком с Python и
терминалом. Для разработки самого проекта — см. `docs/DEVELOPMENT.md`.

## Требования

| Компонент | Минимум | Проверка |
| --- | --- | --- |
| Python | 3.10 | `python3 --version` |
| Ollama | любая актуальная | `ollama --version` |
| `curl` или `wget` | любой | `curl --version` |
| Свободная память | 4 ГБ + под модель | `free -h` |
| Свободное место | 5 ГБ под модели | `df -h ~/.ollama` |

Про память отдельно: модель на 3B в квантовании Q4 занимает 2–3 ГБ
и работает поверх остального. Если у вас 8 ГБ RAM и открытый браузер,
всё влезает, но в притирку. Модель 7B на такой машине работать не будет.

## Быстрый старт

Три команды из корня проекта:

    make install-dev
    make assets
    make run

Открыть в браузере: <http://127.0.0.1:5000>

`make run` скачает HTMX (если не скачан), запустит Flask на
`127.0.0.1:5000` и будет писать логи в stdout. Останов — `Ctrl+C`.

В отдельном терминале должна работать Ollama:

    ollama serve

И должна быть скачана хотя бы одна модель:

    ollama pull llama3.2:3b

Если `ollama serve` уже запущен как systemd-сервис — ничего делать
не нужно, `make run` его увидит.

## Что делает `make install-dev`

- создаёт виртуальное окружение `.venv/` в корне проекта;
- ставит в него runtime-зависимости (Flask, mistune, ollama-python);
- ставит dev-инструменты (pytest, ruff, mypy, coverage);
- устанавливает сам пакет в режиме editable (`pip install -e .`).

Все зависимости остаются внутри `.venv/`. Система не затрагивается.

Проверить, что установилось:

    .venv/bin/python --version
    .venv/bin/pip list | grep -E 'Flask|mistune|ollama|pytest|ruff|mypy'

## Ручная установка (без `make`)

Если `make` недоступен (например, на Windows без WSL):

    python3 -m venv .venv
    # Linux/macOS:
    source .venv/bin/activate
    # Windows (PowerShell):
    #   .venv\Scripts\Activate.ps1

    pip install --upgrade pip
    pip install -e '.[dev]'
    ./scripts/fetch_assets.sh
    python app.py

То же, что и `make install-dev && make assets && make run`, только
командами.

## Автоматизированная установка

Одна команда, которая делает все шаги и заодно проверяет Ollama:

    ./scripts/install.sh

Скрипт:

1. проверяет наличие `python3`;
2. создаёт `.venv/`, если его нет;
3. ставит зависимости;
4. скачивает HTMX в `mini_llm_ui/static/`;
5. проверяет, что `ollama` есть в `PATH`;
6. проверяет, что `ollama serve` отвечает на `127.0.0.1:11434`;
7. скачивает `llama3.2:3b`, если её нет (только если её нет);
8. печатает инструкцию по запуску.

**Скрипт ничего не переустанавливает.** Если Ollama уже стоит и модель
уже скачана — он просто проходит проверки и завершается. Никаких
изменений за пределами директории проекта не делает.

Чтобы указать другую модель (уже имеющуюся в системе):

    OLLAMA_MODEL=qwen2.5-coder:3b ./scripts/install.sh

## Настройка

### Переменные окружения

Скопируйте шаблон и отредактируйте:

    cp .env.example .env

Файл `.env` **не подхватывается автоматически** — это просто шаблон.
Экспортируйте переменные вручную или через `direnv`, `dotenv`, systemd.

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `OLLAMA_MODEL` | `llama3.2:3b` | Модель для генерации |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Адрес сервера Ollama |
| `SECRET_KEY` | `data/secret_key` | Ключ подписи сессий |

### `SECRET_KEY`

Если не задан, при первом старте генерируется случайный ключ и
сохраняется в `data/secret_key` с правами `0600`. Между перезапусками
он не меняется — сессии пользователя не сбрасываются.

Удаление `data/secret_key` = сброс всех сессий. Полезно, если
подозреваете, что кто-то узнал ключ.

### Лимиты

Значения по умолчанию лежат в `mini_llm_ui/constants.py`. Меняются
только правкой файла.

| Константа | Значение | Смысл |
| --- | --- | --- |
| `MAX_FILE_SIZE_BYTES` | 256 KiB | Лимит на одно вложение |
| `MAX_ATTACHMENT_TOTAL_SIZE_BYTES` | 100 KiB | Суммарно на чат |
| `MAX_HISTORY_MESSAGES` | 20 | Последних сообщений уходит в модель |
| `MAX_REQUEST_SIZE_BYTES` | 4 MiB | HTTP-запрос целиком |
| `STREAM_POLL_INTERVAL_MS` | 700 | Интервал polling во время стрима |

## Запуск в продакшене

Если нужен не dev-сервер, а WSGI:

    source .venv/bin/activate
    gunicorn -w 1 -b 127.0.0.1:5000 wsgi:app

**Только один воркер.** `StreamManager` хранит активные стримы в памяти
процесса. `-w 2` и больше сломают polling и резервацию слотов. На N100
этого достаточно — параллелизм всё равно ограничен Ollama-сервером.

Для systemd — пример юнита (замените `User`, `WorkingDirectory`
и путь к `gunicorn`):

    [Unit]
    Description=mini-llm-ui
    After=network.target ollama.service

    [Service]
    Type=simple
    User=you
    WorkingDirectory=/home/you/mini-llm-ui
    Environment=OLLAMA_MODEL=llama3.2:3b
    ExecStart=/home/you/mini-llm-ui/.venv/bin/gunicorn -w 1 -b 127.0.0.1:5000 wsgi:app
    Restart=on-failure

    [Install]
    WantedBy=multi-user.target

## Обновление

Если проект установлен из git-репозитория:

    git pull
    .venv/bin/pip install -e '.[dev]'
    # при изменении структуры/static:
    ./scripts/fetch_assets.sh

Если из pip — переустановить:

    .venv/bin/pip install --force-reinstall -e .

## Удаление

    rm -rf .venv
    rm -rf data uploads
    rm -f .env

Это удалит виртуальное окружение, чаты, вложения и локальный конфиг.
Сам проект (папка с кодом) остаётся.

Модели Ollama удаляются отдельно:

    ollama rm llama3.2:3b

## Что дальше

- `docs/TROUBLESHOOTING.md` — если что-то не работает.
- `docs/SECURITY.md` — модель угроз и рекомендации.
- `docs/ARCHITECTURE.md` — как устроен проект.
- `README.md` — краткий обзор и команды.
