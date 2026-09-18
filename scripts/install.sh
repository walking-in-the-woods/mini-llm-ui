#!/usr/bin/env bash
# Полный сценарий установки mini-llm-ui на чистую систему (Linux/macOS).
# Требуется: python3.10+, curl или wget, установленная и запущенная Ollama.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

MODEL="${OLLAMA_MODEL:-llama3.2:3b}"

echo "==> Проверка Python"
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 не найден" >&2
  exit 1
fi
python3 --version

echo "==> Виртуальное окружение"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Установка зависимостей из lock-файла"
if [ ! -f requirements.lock ]; then
  echo "requirements.lock не найден." >&2
  echo "Он должен быть в репозитории. Проверьте, что клонировали полностью." >&2
  exit 1
fi
pip install --upgrade pip >/dev/null
pip install -r requirements.lock
pip install -e . --no-deps

echo "==> Вендоринг HTMX"
./scripts/fetch_assets.sh

echo "==> Проверка Ollama"
if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama не найдена в PATH. Установите: https://ollama.com/download" >&2
  exit 1
fi
if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "Ollama не отвечает на 127.0.0.1:11434."
  echo "Запустите в отдельном терминале: ollama serve"
  exit 1
fi

echo "==> Загрузка модели '$MODEL' (если отсутствует)"
if ! ollama list | awk '{print $1}' | grep -qx "$MODEL"; then
  ollama pull "$MODEL"
fi

echo
echo "Готово. Запуск:"
echo "  source .venv/bin/activate"
echo "  make run"
echo "Открыть: http://127.0.0.1:5000"