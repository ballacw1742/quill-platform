# quill-agent-orchestrator (Phase A P0 spike).
# Build context: agent-cloud/ dir:  docker build -t quill-agent-orchestrator agent-cloud/
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN pip install --upgrade pip && pip install \
    "fastapi>=0.110" "uvicorn[standard]>=0.27" "anthropic>=0.40" \
    "httpx>=0.27" "psycopg[binary]>=3.1"
COPY main.py /app/main.py
EXPOSE 8080
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
