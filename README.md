# mini-llm-ui

Компактный локальный веб-интерфейс для работы с моделями Ollama.
Рассчитан на слабое железо (Intel N100, 8 ГБ RAM, без GPU).

[![CI](https://github.com/walking-in-the-woods/mini-llm-ui/actions/workflows/ci.yml/badge.svg)](https://github.com/walking-in-the-woods/mini-llm-ui/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

## Что это

Локальный чат-интерфейс к Ollama. Работает в браузере, слушает
только `127.0.0.1`, хранит историю в SQLite. Никаких облаков,
аккаунтов, телеметрии.

Возможности:

- Список чатов в левой панели, переключение одним кликом.
- Markdown в режиме чтения, редактирование — в `<textarea>`.
- Загрузка `.md` / `.txt` — содержимое один раз уходит модели
  system-сообщением.
- Стриминг ответа (polling 700 мс), во время генерации показывается
  plain text, Markdown рендерится по завершении.
- Кнопка остановки генерации (мягкая, см. `docs/TROUBLESHOOTING.md`).
- Экспорт любого сообщения в `.md`.
- Автоматическое имя чата по первому сообщению.
- Возобновление polling после перезагрузки страницы.

## Требования

- Python 3.10+
- Ollama, запущенная локально
- `curl` или `wget` (для скачивания HTMX при установке)

## Установка

Три команды:

    make install-dev
    make assets
    make run

Открыть <http://127.0.0.1:5000>.

Подробности, варианты (ручная установка, продакшен, systemd) —
в `docs/INSTALL.md`.

## Управление

| Команда | Что делает |
| --- | --- |
| `make install` | venv + runtime-зависимости |
| `make install-dev` | + ruff, mypy, pytest, coverage |
| `make assets` | скачать HTMX в `mini_llm_ui/static/` |
| `make run` | dev-сервер на `127.0.0.1:5000` |
| `make test` | pytest |
| `make test-cov` | pytest с покрытием |
| `make lint` | ruff check |
| `make fmt` | ruff format |
| `make typecheck` | mypy strict |
| `make check` | lint + typecheck + test |
| `make clean` | удалить артефакты |

## Конфигурация

Переменные окружения:

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `OLLAMA_MODEL` | `llama3.2:3b` | Модель для генерации |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Адрес сервера Ollama |
| `SECRET_KEY` | `data/secret_key` | Ключ подписи сессий |

Если `SECRET_KEY` не задан, при первом старте создаётся случайный
и сохраняется в `data/secret_key` с правами `0600`. Между
перезапусками не меняется.

## Запуск в продакшене

    gunicorn -w 1 -b 127.0.0.1:5000 wsgi:app

**Только один воркер.** `StreamManager` хранит активные стримы в
памяти процесса. Второй воркер сломает polling и резервацию слотов.

## Документация

- [`docs/INSTALL.md`](docs/INSTALL.md) — установка, конфигурация,
  systemd, обновление, удаление.
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) — 13 типовых
  проблем и их решения.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — как устроен
  проект, ключевые инженерные решения.
- [`docs/SECURITY.md`](docs/SECURITY.md) — модель угроз, принятые
  меры, сознательные ограничения.
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) — для разработчиков:
  тесты, линтеры, релизный процесс.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — как сообщить о проблеме
  или предложить изменение.
- [`CHANGELOG.md`](CHANGELOG.md) — история версий.

## Безопасность

Приложение локальное, слушает `127.0.0.1`, аутентификации нет.
Кратко о защите:

- Markdown рендерится с `escape=True` — prompt injection в
  загруженном файле не приведёт к XSS.
- CSRF-защита на всех POST-запросах.
- Host allow-list против DNS rebinding.
- `SECRET_KEY` создаётся с правами `0600`.

Полная модель угроз и conscious trade-offs — в `docs/SECURITY.md`.

Нашли уязвимость — открывайте issue с тегом `security` или пишите
мейнтейнеру приватно.

## Лицензия

MIT. См. [`LICENSE`](LICENSE).
