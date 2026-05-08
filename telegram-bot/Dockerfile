# Quill Telegram bot — slim Python image
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install bot package
COPY telegram-bot/pyproject.toml /app/telegram-bot/pyproject.toml
COPY telegram-bot/quill_bot /app/telegram-bot/quill_bot
COPY telegram-bot/README.md /app/telegram-bot/README.md
RUN pip install -e /app/telegram-bot

# Default command. Override in compose if needed.
CMD ["quill-bot", "run"]
