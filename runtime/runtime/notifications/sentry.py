"""Sentry init for the runtime service (Sprint 2.4).

Mirror of `api/app/services/sentry.py` but tagged `service=runtime`.

Runtime telemetry rules:
  - Tag every event with: service=runtime, environment, agent_id (when known),
    approval_id (when known), run_id (the AgentRun.id when running orchestrator).
  - PII redaction is critical here: agent inputs/outputs may contain RFI text,
    submittal specs, schedule deltas. We never auto-include payloads.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import sentry_sdk

log = logging.getLogger("quill.runtime.sentry")

_initialized = False

_PII_KEYS = frozenset(
    {"input", "output", "payload", "prompt", "completion", "response",
     "secret", "token", "authorization", "private_key"}
)


def _scrub(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
    try:
        extra = event.get("extra") or {}
        for k in list(extra.keys()):
            if k.lower() in _PII_KEYS:
                extra[k] = "<redacted>"
        for crumb in event.get("breadcrumbs", {}).get("values", []) or []:
            data = crumb.get("data") or {}
            for k in list(data.keys()):
                if k.lower() in _PII_KEYS:
                    data[k] = "<redacted>"
        # Defensive: drop any top-level message body that looks like a payload
        msg = event.get("message")
        if isinstance(msg, dict) and "formatted" in msg:
            f = msg["formatted"]
            # Heuristic: very long messages with JSON braces are scrubbed.
            if isinstance(f, str) and len(f) > 4000 and "{" in f and "}" in f:
                msg["formatted"] = "<redacted-large-payload>"
    except Exception:  # noqa: BLE001
        pass
    return event


def init(force: bool = False) -> bool:
    """Initialize Sentry for the runtime. Idempotent + safe with no DSN."""
    global _initialized
    if _initialized and not force:
        return bool(sentry_sdk.Hub.current.client and sentry_sdk.Hub.current.client.dsn)

    dsn = os.environ.get("SENTRY_DSN_RUNTIME") or os.environ.get("SENTRY_DSN", "")
    env = os.environ.get("ENVIRONMENT", "dev")

    if dsn:
        sentry_sdk.init(
            dsn=dsn,
            traces_sample_rate=0.1,
            environment=env,
            release=f"quill-runtime@{_runtime_version()}",
            send_default_pii=False,
            before_send=_scrub,
        )
        log.info("sentry initialized for service=runtime env=%s", env)
    else:
        log.info("sentry DSN missing — service=runtime running without remote reporting")

    with sentry_sdk.configure_scope() as scope:
        scope.set_tag("service", "runtime")
        scope.set_tag("environment", env)

    _initialized = True
    return bool(dsn)


def _runtime_version() -> str:
    try:
        from runtime import __version__
        return __version__
    except Exception:  # noqa: BLE001
        return "0.0.0"


def tag_agent(agent_id: str | None) -> None:
    if not agent_id:
        return
    with sentry_sdk.configure_scope() as scope:
        scope.set_tag("agent_id", agent_id)


def tag_approval(approval_id: str | None) -> None:
    if not approval_id:
        return
    with sentry_sdk.configure_scope() as scope:
        scope.set_tag("approval_id", approval_id)


def tag_run(run_id: str | None) -> None:
    if not run_id:
        return
    with sentry_sdk.configure_scope() as scope:
        scope.set_tag("run_id", run_id)


def capture_message(msg: str, level: str = "info", **tags: Any) -> str | None:
    with sentry_sdk.push_scope() as scope:
        for k, v in tags.items():
            if v is not None:
                scope.set_tag(k, str(v))
        return sentry_sdk.capture_message(msg, level=level)


def capture_exception(exc: BaseException | None = None, **tags: Any) -> str | None:
    with sentry_sdk.push_scope() as scope:
        for k, v in tags.items():
            if v is not None:
                scope.set_tag(k, str(v))
        return sentry_sdk.capture_exception(exc)
