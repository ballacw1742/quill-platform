# quill-agent-orchestrator — Phase A platform core.
# Build context: agent-cloud/ dir:  docker build -t quill-agent-orchestrator agent-cloud/
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt
COPY main.py /app/main.py
COPY app /app/app
EXPOSE 8080
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
