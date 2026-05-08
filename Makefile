.PHONY: install dev test lint migrate seed smoke clean docker-up docker-down audit-verify audit-replay

PY ?= python3
VENV ?= .venv
PIP := $(VENV)/bin/pip
PYBIN := $(VENV)/bin/python
UVICORN := $(VENV)/bin/uvicorn
PYTEST := $(VENV)/bin/pytest
RUFF := $(VENV)/bin/ruff
ALEMBIC := $(VENV)/bin/alembic

$(VENV)/bin/python:
	$(PY) -m venv $(VENV)
	$(PIP) install --upgrade pip

install: $(VENV)/bin/python
	$(PIP) install -e ".[dev]"

docker-up:
	docker-compose up -d db
	@echo "Waiting for Postgres..."
	@sleep 3

docker-down:
	docker-compose down

migrate: install
	$(ALEMBIC) -c api/alembic.ini upgrade head

seed: install
	$(VENV)/bin/python -m scripts.seed_dev

dev: install
	$(UVICORN) app.main:app --app-dir api --reload --host 0.0.0.0 --port 8000

test: install
	$(PYTEST) -q

lint: install
	$(RUFF) check api

smoke:
	$(VENV)/bin/python api/scripts/post_test_approval.py

audit-verify: install
	$(VENV)/bin/python api/scripts/audit_verify_run.py --drain --triggered-by=make

audit-replay: install
	$(VENV)/bin/python api/scripts/audit_mirror_replay.py --since $${SINCE:-2026-05-01} --until $${UNTIL:-$$(date +%Y-%m-%d)}

clean:
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache **/__pycache__ build dist *.egg-info quill_dev.db
