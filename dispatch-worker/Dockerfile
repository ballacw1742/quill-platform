# quill-dispatch-worker — the four Quill dispatch loops on Cloud Run (Sprint 5.5).
# Build context is the REPO ROOT:
#   docker build -f dispatch-worker/Dockerfile -t quill-dispatch-worker .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Runtime package (dispatchers, agent runtime, state store) + worker extras.
COPY runtime /app/runtime
RUN pip install --upgrade pip \
    && pip install /app/runtime[worker] "fastapi>=0.110" "uvicorn[standard]>=0.27"

# The estimator dispatcher imports one pure-python shared module from the API
# source tree (app.services.estimator_input — no I/O, no API deps). We mount
# the api source on PYTHONPATH rather than duplicating the module.
COPY api/app/__init__.py /app/api/app/__init__.py
COPY api/app/services/__init__.py /app/api/app/services/__init__.py
COPY api/app/services/estimator_input.py /app/api/app/services/estimator_input.py
ENV PYTHONPATH=/app/api

# Vendored prompts + schemas snapshot (see dispatch-worker/prompts/README.md
# for source repo + commit). No network dependency on the prompts repo.
COPY dispatch-worker/prompts /app/prompts
ENV PROMPTS_REPO_PATH=/app/prompts

COPY dispatch-worker/main.py /app/main.py

EXPOSE 8080
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
