.PHONY: install dev test lint migrate seed smoke clean docker-up docker-down bot-install bot-dev bot-test bot-mint-pair audit-verify audit-replay mock-install mock-bootstrap mock-start mock-stop mock-status mock-test daily-brief-now triage-dispatcher triage-replay classify-dispatcher estimator-dispatcher restart-all dev-chat-worker deploy-watcher contract-dispatcher

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

# ---------------------------------------------------------------------------
# Continuous triage dispatcher (Phase F.1)
# ---------------------------------------------------------------------------
# Runs the TriageDispatcher in the foreground. Reads .env so
# QUEUE_API_URL / AGENT_SHARED_SECRET / TRIAGE_* vars are honored.
triage-dispatcher:
	@bash -c 'set -a; [ -f .env ] && source .env; set +a; \
		QUILL_API_URL=$${QUILL_API_URL:-http://localhost:8000} \
		AGENT_SHARED_SECRET=$${AGENT_SHARED_SECRET:-dev-agent-secret-change-me} \
		TRIAGE_EVENT_SOURCE=$${TRIAGE_EVENT_SOURCE:-mock} \
		TRIAGE_POLL_INTERVAL_SECONDS=$${TRIAGE_POLL_INTERVAL_SECONDS:-5} \
		exec $(VENV)/bin/quill-runtime triage start'

# ---------------------------------------------------------------------------
# Classification dispatcher (Phase G.5)
# ---------------------------------------------------------------------------
# Runs the ClassificationDispatcher in the foreground. Reads .env so
# QUILL_API_URL / AGENT_SHARED_SECRET / CLASSIFY_POLL_INTERVAL_SECONDS
# are honored.
classify-dispatcher:
	@bash -c 'set -a; [ -f .env ] && source .env; set +a; \
		QUILL_API_URL=$${QUILL_API_URL:-http://localhost:8000} \
		AGENT_SHARED_SECRET=$${AGENT_SHARED_SECRET:-dev-agent-secret-change-me} \
		CLASSIFY_POLL_INTERVAL_SECONDS=$${CLASSIFY_POLL_INTERVAL_SECONDS:-10} \
		exec $(VENV)/bin/quill-runtime classify start'

triage-replay:
	@bash -c 'set -a; [ -f .env ] && source .env; set +a; \
		QUILL_API_URL=$${QUILL_API_URL:-http://localhost:8000} \
		AGENT_SHARED_SECRET=$${AGENT_SHARED_SECRET:-dev-agent-secret-change-me} \
		exec $(VENV)/bin/quill-runtime triage replay $${LOG:-mock-data/_state/dispatch.log}'

# ---------------------------------------------------------------------------
# Estimator dispatcher (Phase G.6)
# ---------------------------------------------------------------------------
# Runs the EstimatorDispatcher in the foreground. Reads .env so
# QUILL_API_URL / AGENT_SHARED_SECRET / ESTIMATE_POLL_INTERVAL_SECONDS
# are honored.
# ---------------------------------------------------------------------------
# Dev-chat worker + auto-deploy watcher (Sprint DC.1)
# ---------------------------------------------------------------------------

restart-all:
	@echo "[restart-all] backend..."
	-@kill $$(cat logs/backend.pid 2>/dev/null) 2>/dev/null || true
	@sleep 1
	@nohup .venv/bin/uvicorn app.main:app --app-dir api --host 0.0.0.0 --port 8000 > logs/backend.log 2>&1 & echo $$! > logs/backend.pid
	@echo "[restart-all] frontend hot-reloads via Next dev; nothing to restart"
	@echo "[restart-all] done"

dev-chat-worker:
	@bash -c 'set -a; [ -f .env ] && source .env; set +a; \
	  QUILL_API_URL=$${QUILL_API_URL:-http://localhost:8000} \
	  AGENT_SHARED_SECRET=$${AGENT_SHARED_SECRET:-dev-agent-secret-change-me} \
	  exec $(VENV)/bin/quill-runtime dev-chat start $${DEV_CHAT_FLAGS}'

deploy-watcher:
	@bash -c 'set -a; [ -f .env ] && source .env; set +a; \
	  exec $(VENV)/bin/quill-runtime deploy-watch start'

# ---------------------------------------------------------------------------
estimator-dispatcher:
	@bash -c 'set -a; [ -f .env ] && source .env; set +a; \
		QUILL_API_URL=$${QUILL_API_URL:-http://localhost:8000} \
		AGENT_SHARED_SECRET=$${AGENT_SHARED_SECRET:-dev-agent-secret-change-me} \
		ESTIMATE_POLL_INTERVAL_SECONDS=$${ESTIMATE_POLL_INTERVAL_SECONDS:-10} \
		exec $(VENV)/bin/quill-runtime estimate start'

contract-dispatcher:
	@bash -c 'set -a; [ -f .env ] && source .env; set +a; \
	  QUILL_API_URL=$${QUILL_API_URL:-http://localhost:8000} \
	  AGENT_SHARED_SECRET=$${AGENT_SHARED_SECRET:-dev-agent-secret-change-me} \
	  CONTRACT_POLL_INTERVAL_SECONDS=$${CONTRACT_POLL_INTERVAL_SECONDS:-10} \
	  exec $(VENV)/bin/quill-runtime contract start'
