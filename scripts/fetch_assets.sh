#!/usr/bin/env bash
# Скачивает вендоренные ассеты в mini_llm_ui/static/.
# Используется один раз при развёртывании; в репозитории файлы не хранятся.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="$HERE/mini_llm_ui/static"
mkdir -p "$TARGET_DIR"

HTMX_URL="https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js"
HTMX_OUT="$TARGET_DIR/htmx.min.js"

if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$HTMX_URL" -o "$HTMX_OUT"
elif command -v wget >/dev/null 2>&1; then
  wget -q "$HTMX_URL" -O "$HTMX_OUT"
else
  echo "Нужен curl или wget" >&2
  exit 1
fi

echo "Скачано: $HTMX_OUT"
