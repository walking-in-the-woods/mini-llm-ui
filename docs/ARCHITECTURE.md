# Архитектура

Документ описывает структуру проекта, поток данных и ключевые
инженерные решения. Рассчитан на разработчика, который впервые
открыл код и хочет понять, где что лежит и почему сделано именно так.

## Обзор

mini-llm-ui — монолитное Flask-приложение с серверным рендерингом.
Никаких JS-фреймворков, никакого билд-степа. Стек выбран под целевую
машину (Intel N100, 8 ГБ RAM, без GPU): приложение должно оставлять
как можно больше памяти Ollama с её моделью.

    Браузер
    ├── Jinja2-шаблоны (HTML)
    ├── HTMX (точечные обновления через HX-запросы)
    └── app.css
              │
              │ HTTP на 127.0.0.1:5000
              ▼
    Flask (mini_llm_ui/)
    ├── security.py — Host allow-list, CSRF
    ├── routes/ — HTTP-обработчики
    ├── services/ — Ollama, Markdown, файлы, StreamManager
    ├── db.py + models.py — SQLite
    └── config.py + constants.py
              │
              ├── SQLite: data/chat.db (WAL)
              └── HTTP на 127.0.0.1:11434
                        │
                        ▼
                    Ollama
                        │
                        └── модель (llama3.2:3b и т. п.)

## Раскладка

    mini_llm_ui/
    ├── __init__.py           # __version__, экспорт create_app
    ├── __main__.py           # python -m mini_llm_ui
    ├── app.py                # фабрика create_app()
    ├── config.py             # AppConfig, frozen dataclass
    ├── constants.py          # все числа и шаблоны сообщений
    ├── exceptions.py         # иерархия ожидаемых ошибок
    ├── logging_config.py     # однократная настройка logging
    ├── security.py           # Host allow-list, CSRF, HTMX-ошибки
    ├── db.py                 # соединения, схема, миграция-в-одну-сторону
    ├── models.py             # чаты, сообщения, вложения
    ├── routes/
    │   ├── __init__.py       # register_blueprints()
    │   ├── chat_routes.py    # основной UI + стриминг
    │   ├── file_routes.py    # загрузка/удаление вложений
    │   └── export_routes.py  # экспорт сообщения в .md
    ├── services/
    │   ├── __init__.py
    │   ├── markdown_service.py   # mistune, escape=True
    │   ├── file_service.py       # валидация .md/.txt
    │   ├── ollama_service.py     # OllamaService + сборка промпта
    │   └── stream_manager.py     # StreamManager (stateful)
    ├── templates/            # Jinja2
    └── static/               # app.css + htmx.min.js

Точки входа: `app.py` (dev), `wsgi.py` (prod), `python -m mini_llm_ui`
(эквивалент `python app.py`).

## Ключевые решения

### 1. Server-side rendering + HTMX вместо SPA

React/Vue/Svelte дают гибкость, но требуют Node.js, сборку и рантайм
30–50 МБ. На N100 это заметная доля бюджета. HTMX даёт 90 % нужной
интерактивности: точечные swap-ы фрагментов, отправка форм, polling.
Всё, что не помещается в HTMX, добирается 20 строками vanilla JS в
`base.html`.

### 2. SQLite в WAL-режиме

WAL (Write-Ahead Logging) позволяет читателям не блокировать
писателей. Критично, потому что фоновый поток стриминга пишет в БД
одновременно с HTTP-запросами от UI. Плюс `busy_timeout = 5000` —
если всё-таки столкнулись, ждём 5 секунд, а не падаем.

Схема не требует миграций: `CREATE TABLE IF NOT EXISTS` в `db.py`
покрывает обновление с пустой базы. При первом изменении схемы
появится `PRAGMA user_version` и ручные миграции — но пока рано.

### 3. StreamManager как инстанс, а не модуль

Все активные стримы живут в `app.extensions['stream_manager']`, а не
в модульных глобалах. Это даёт:

- **Изоляцию тестов.** Каждый `create_app()` создаёт свой менеджер.
  `monkeypatch.setattr(module, '_streams', {})` больше не нужен.
- **Явные зависимости.** `StreamManager(config, ollama_service)`
  видно в сигнатуре, а не размазано по импортам.
- **Возможность нескольких инстансов** в одном процессе (на будущее).

Плата — доступ через `current_app.extensions[...]`, но это две
строки в хелперах `_stream_manager()` / `_app_config()`.

### 4. Вложения — один раз в system-сообщении

Раньше (в первой итерации проекта) вложения подставлялись в каждое
user-сообщение. Это плохо: если файл на 100 КБ, и в чате 20
сообщений, каждый запрос отправляет в модель 20 × 100 КБ контекста.
На N100 это приводит к out-of-memory на стороне Ollama.

Сейчас `build_prompt_messages` собирает вложения **один раз** в
system-сообщении в начале истории. Общий размер вложений ограничен
`MAX_ATTACHMENT_TOTAL_SIZE_BYTES = 100 КБ` на чат.

### 5. Стриминг через polling, а не SSE/WebSocket

Олли-сервер на слабой машине отдаёт 3–10 токенов в секунду. Обновление
UI раз в 700 мс визуально неотличимо от SSE, но:

- нет долгоживущих соединений — проще с прокси и systemd;
- нет отдельного канала — polling идёт через тот же Flask;
- HTMX умеет polling одной строкой `hx-trigger="every 700ms"`.

Каждый poll — это HTTP GET, который читает `StreamManager.get_snapshot`
и рендерит фрагмент. Poll завершается сам, когда стрим `done`:
элемент заменяется на `message.html` без `hx-trigger`.

### 6. Кэширование HTML на этапе записи

Поле `messages.html_content` хранит готовый HTML-рендер Markdown.
Заполняется один раз — при сохранении отредактированного сообщения
или в `StreamManager._persist`. Не при каждом открытии чата.

Это снимает нагрузку с mistune при частых перезагрузках страницы
(а polling → перезагрузки частые).

### 7. Восстановление после фейла БД

Если `_persist` не смог записать финальный контент (диск полный,
БД заблокирована), контент:

1. остаётся в памяти `StreamManager` на 5 минут;
2. сохраняется в `data/recovery/msg_<id>.md` через `os.replace`
   (атомарная замена);
3. `poll_message` при следующем обращении подменяет данные из БД
   на данные из памяти.

Пользователь видит ответ даже при сломанной БД. Восстановление
файла в БД — ручное (перенести содержимое в поле `content`).

## Поток отправки сообщения

Самое сложное место проекта. Разбираем по шагам, потому что порядок
операций критичен.

    POST /chat/<id>/send
      │
      ├─ 1. Валидация content (непустой, strip)
      │
      ├─ 2. Пре-чек has_active_stream(chat_id)
      │     └─ если занят → 409 Conflict + HX-Retarget → выход
      │
      ├─ 3. models.add_message(role='user')
      │     └─ пишет в БД + обновляет chats.updated_at
      │
      ├─ 4. Собрать history + attachments из БД
      │     └─ build_prompt_messages() формирует промпт БЕЗ ассистента
      │
      ├─ 5. models.add_message(role='assistant', content='') — placeholder
      │
      ├─ 6. stream_manager.try_reserve(chat_id, assistant_id)
      │     └─ если отказ (гонка после шага 2):
      │         ├─ delete_message(assistant_id)
      │         ├─ delete_message(user_id)
      │         └─ 409 + HX-Retarget → выход
      │
      ├─ 7. stream_manager.start(...) — фоновый поток
      │     └─ при исключении: полный откат, raise
      │
      ├─ 8. models.auto_title_from_first_message()
      │     └─ переименование чата по первому сообщению
      │
      └─ 9. Рендер message_pair.html → HTMX вставляет в #messages

**Почему user-сообщение пишется до reserve.** Если писать после, то
при занятом слоте мы не сможем сообщить пользователю, какое именно
сообщение не отправилось. А если reserve падает — мы откатываем оба
сообщения, включая user.

**Почему placeholder пишется до reserve.** `try_reserve` требует
`message_id` как ключ в `self._streams`. Можно было бы использовать
`chat_id` как ключ и не создавать placeholder, но тогда:

- при `has_active_stream`, проверяемом по `chat_id`, теряется
  симметрия «одна запись = один стрим»;
- в БД нет места, куда `StreamManager._persist` запишет результат.

Placeholder + reserve с откатом — самый чистый вариант.

## Фоновый поток стрима

    StreamManager.start()
      └─ threading.Thread(_run_worker)

    _run_worker(message_id, model, messages):
      │
      ├─ generator = self._ollama.stream_chat(model, messages)
      │
      ├─ for chunk in generator:
      │     with self._lock:
      │         state = self._streams.get(message_id)
      │         if cancelled: break
      │         state.chunks.append(chunk)
      │
      ├─ generator.close() — освобождает httpx-соединение
      │
      ├─ _finalize_state() — флаги done/cancelled, маркер отмены
      │
      ├─ _persist() → UPDATE messages SET content, html_content
      │     └─ при успехе удаляет recovery-файл, если он был
      │
      ├─ при фейле _persist → _write_recovery_file()
      │
      └─ threading.Timer(delay, _cleanup)
            delay = 60 с (успех) или 300 с (фейл БД)

Все обращения к `self._streams` — под `self._lock`. Вне lock:

- HTTP-запрос к Ollama (может длиться десятки секунд);
- запись в БД (I/O);
- запись recovery-файла (I/O).

Это критично: если бы мы держали lock во время HTTP-запроса, UI
не смог бы читать снапшот параллельно, и всё встало бы.

## Безопасность

Модель угроз и принятые меры — в `docs/SECURITY.md`. Здесь только
архитектурная сводка:

- `security.py` изолирован: чистые функции без Flask-контекста
  (`is_allowed_host`), тестируются без приложения.
- Host allow-list и CSRF — `before_request`-хуки, регистрируются в
  `create_app`.
- Markdown рендерится с `escape=True` — сырой HTML из ответов модели
  и файлов экранируется.
- Сервер слушает только `127.0.0.1`.

## Что осознанно НЕ сделано

- **Аутентификация.** Приложение локальное, любой пользователь машины
  видит чаты. Для домашнего ноутбука этого достаточно.
- **Миграции БД.** Схема менялась один раз (при переходе от прототипа).
  Alembic избыточен, `CREATE IF NOT EXISTS` покрывает обновления.
- **Вебсокеты.** Polling 700 мс — компромисс между плавностью UI и
  потреблением ресурсов.
- **Плагины/расширения.** Монолит, расширяется правкой кода.
- **Мультиязычность UI.** Только русский. Английский — при
  необходимости добавить `.po`-файлы.

## См. также

- `docs/DEVELOPMENT.md` — как запускать тесты, линтеры, отлаживать.
- `docs/SECURITY.md` — модель угроз.
- `docs/INSTALL.md` — установка.
- `docs/TROUBLESHOOTING.md` — типовые проблемы.
