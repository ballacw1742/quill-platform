.PHONY: install dev test lint migrate seed smoke clean docker-up docker-down bot-install bot-dev bot-test bot-mint-pair audit-verify audit-replay mock-install mock-bootstrap mock-start mock-stop mock-status mock-test daily-brief-now

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

# ---------------------------------------------------------------------------
# Telegram bot (Sprint 2.4)
# ---------------------------------------------------------------------------
bot-install: $(VENV)/bin/python
	$(PIP) install -e telegram-bot[dev]

bot-dev: bot-install
	@echo "Starting Quill Telegram bot in dev mode (fake-token if TELEGRAM_BOT_TOKEN unset)..."
	QUILL_API_URL=$${QUILL_API_URL:-http://localhost:8000} \
	$(VENV)/bin/quill-bot run

bot-test: bot-install
	cd telegram-bot && ../$(PYTEST) -q

bot-mint-pair: bot-install
	@if [ -z "$(EMAIL)" ]; then echo "Usage: make bot-mint-pair EMAIL=charles@x.com" >&2; exit 2; fi
	$(VENV)/bin/quill-bot mint-pair --email $(EMAIL)

# ---------------------------------------------------------------------------
# Mock data sources (Sprint 3)
# ---------------------------------------------------------------------------
MOCK_LOG ?= mock-data/_state/mock-data.log
MOCK_DAEMON_PID ?= mock-data/_state/mock-daemon.pid

mock-install: $(VENV)/bin/python
	$(PIP) install -e mock-data

mock-bootstrap: mock-install
	$(VENV)/bin/quill-mock bootstrap

mock-start: mock-install
	@mkdir -p mock-data/_state
	@if [ -f $(MOCK_DAEMON_PID) ] && kill -0 $$(cat $(MOCK_DAEMON_PID)) 2>/dev/null; then \
		echo "mock-data already running (pid=$$(cat $(MOCK_DAEMON_PID)))"; exit 0; \
	fi
	@nohup $(VENV)/bin/quill-mock start --fast > $(MOCK_LOG) 2>&1 & echo $$! > $(MOCK_DAEMON_PID)
	@sleep 1
	@echo "mock-data started (pid=$$(cat $(MOCK_DAEMON_PID))) — tail $(MOCK_LOG)"

mock-stop: mock-install
	-@$(VENV)/bin/quill-mock stop || true
	-@if [ -f $(MOCK_DAEMON_PID) ]; then \
		PID=$$(cat $(MOCK_DAEMON_PID)); kill $$PID 2>/dev/null || true; rm -f $(MOCK_DAEMON_PID); \
	fi
	@echo "mock-data stopped"

mock-status: mock-install
	@$(VENV)/bin/quill-mock status

mock-test: mock-install
	cd mock-data && ../$(PYTEST) -q

daily-brief-now: mock-install
	QUILL_API_URL=$${QUILL_API_URL:-http://localhost:8000} \
	AGENT_SHARED_SECRET=$${AGENT_SHARED_SECRET:-dev-agent-secret-change-me} \
	$(VENV)/bin/python runtime/scripts/daily_brief_pipeline.py
