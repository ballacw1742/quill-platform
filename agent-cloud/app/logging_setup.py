"""Structured JSON logging with request/tenant/agent/session context.

Cloud Logging picks up the `severity` field from JSON lines on stdout.
Context is carried in contextvars so every log line inside a request
automatically includes request_id / tenant_id / agent_id / session_id.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
tenant_id_var: ContextVar[str | None] = ContextVar("tenant_id", default=None)
agent_id_var: ContextVar[str | None] = ContextVar("agent_id", default=None)
session_id_var: ContextVar[str | None] = ContextVar("session_id", default=None)

_SEVERITY = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARNING": "WARNING",
    "ERROR": "ERROR",
    "CRITICAL": "CRITICAL",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "severity": _SEVERITY.get(record.levelname, "DEFAULT"),
            "time": datetime.now(timezone.utc).isoformat(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, var in (
            ("request_id", request_id_var),
            ("tenant_id", tenant_id_var),
            ("agent_id", agent_id_var),
            ("session_id", session_id_var),
        ):
            val = var.get()
            if val is not None:
                entry[key] = val
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        # Extras passed via logger.info(..., extra={"extra_fields": {...}})
        extra_fields = getattr(record, "extra_fields", None)
        if isinstance(extra_fields, dict):
            entry.update(extra_fields)
        return json.dumps(entry, default=str)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    # uvicorn access logs stay readable but route through the same handler
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
