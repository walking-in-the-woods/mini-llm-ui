.PHONY: help install install-dev lock assets run test test-cov lint fmt typecheck check clean

PYTHON ?= python3

help:
	@echo "Цели:"
	@echo "  install       — создать venv и поставить только базовые зависимости из uv.lock"
	@echo "  install-dev   — то же + dev-инструменты (ruff, mypy, pytest, coverage)"
	@echo "  lock          — пересобрать uv.lock из pyproject.toml"
	@echo "  assets        — скачать HTMX в mini_llm_ui/static/"
	@echo "  run           — запустить приложение (python app.py)"
	@echo "  test          — pytest"
	@echo "  test-cov      — pytest с покрытием"
	@echo "  lint          — ruff check"
	@echo "  fmt           — ruff format"
	@echo "  typecheck     — mypy strict"
	@echo "  check         — lint + typecheck + test (полный прогон)"
	@echo "  clean         — удалить артефакты и виртуальное окружение (кроме uv.lock)"

install:
	uv sync --locked

install-dev:
	uv sync --locked --extra dev

lock:
	uv lock

assets:
	./scripts/fetch_assets.sh

run: assets
	uv run python app.py

test:
	uv run pytest

test-cov:
	uv run pytest --cov --cov-report=term-missing

lint:
	uv run ruff check .

fmt:
	uv run ruff format .

typecheck:
	uv run mypy

check: lint typecheck test

clean:
	rm -rf .venv .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +