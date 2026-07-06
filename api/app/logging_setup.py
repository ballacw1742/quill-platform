"""Structured JSON logging."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        # Structured extras carried on the LogRecord. event/method/path/status/
        # duration_ms power the Sprint 5.3 http_request access log line.
        for k in (
            "request_id", "actor", "approval_id",
            "event", "method", "path", "status", "duration_ms",
        ):
            v = getattr(record, k, None)
            if v is not None:
                out[k] = v
        return json.dumps(out, default=str)


def configure_logging(level: str = "INFO") -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [h]
    root.setLevel(level.upper())
    # Quiet down noisy libraries unless we want them.
    logging.getLogger("uvicorn.access").setLevel("INFO")
    logging.getLogger("sqlalchemy.engine").setLevel("WARNING")
