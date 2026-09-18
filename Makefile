.PHONY: help install install-dev lock assets run test test-cov lint fmt typecheck check clean

PYTHON ?= python3
VENV   ?= .venv
PIP    := $(VENV)/bin/pip
PY     := $(VENV)/bin/python

help:
	@echo "Цели:"
	@echo "  install       — создать venv и поставить зависимости из lock-файла"
	@echo "  install-dev   — то же + dev-инструменты (ruff, mypy, pytest, coverage)"
	@echo "  lock          — пересобрать requirements.lock из pyproject.toml"
	@echo "  assets        — скачать HTMX в mini_llm_ui/static/"
	@echo "  run           — запустить приложение (python app.py)"
	@echo "  test          — pytest"
	@echo "  test-cov      — pytest с покрытием"
	@echo "  lint          — ruff check"
	@echo "  fmt           — ruff format"
	@echo "  typecheck     — mypy strict"
	@echo "  check         — lint + typecheck + test (полный прогон)"
	@echo "  clean         — удалить артефакты"

$(VENV):
	$(PYTHON) -m venv $(VENV)

install: $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.lock
	$(PIP) install -e . --no-deps

install-dev: $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.lock
	$(PIP) install -e . --no-deps

lock:
	$(VENV)/bin/pip-compile --generate-hashes --extra dev \
	    --output-file requirements.lock pyproject.toml

assets:
	./scripts/fetch_assets.sh

run: assets
	$(PY) app.py

test:
	$(PY) -m pytest

test-cov:
	$(PY) -m pytest --cov --cov-report=term-missing

lint:
	$(VENV)/bin/ruff check .

fmt:
	$(VENV)/bin/ruff format .

typecheck:
	$(VENV)/bin/mypy

check: lint typecheck test

clean:
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +