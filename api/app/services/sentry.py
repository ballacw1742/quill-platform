"""Sentry initialization wrapper for the API service.

Centralizes init so we can:
  - Tag every event with `service=api`, `environment`, and request/approval/agent/user IDs
  - Strip PII (payloads) defensively before send
  - Init lazily and idempotently from `app.main` lifespan

The actual `sentry_sdk.init` call already happened at module-import time in
`app.main` (legacy from Sprint 1.1). This wrapper supersedes that call: when
`init()` here runs, it re-initializes with the richer config (tags, before_send,
release, env). If SENTRY_DSN_API/SENTRY_DSN is empty we still install a
no-op shim so callers can use `tag_*` / `capture_event` unconditionally.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from app import __version__
from app.config import get_settings

log = logging.getLogger("quill.sentry")

_initialized = False

# Keys we will *never* send to Sentry, even if they show up in extra context.
_PII_KEYS = frozenset(
    {"payload", "password", "secret", "token", "authorization",
     "x-admin", "x-agent-secret", "credential", "private_key"}
)


def _scrub(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
    """Strip payload bodies + sensitive keys from extra/request data.

    Sentry's default `send_default_pii=False` already drops cookies/headers,
    but request bodies leak through breadcrumbs and `extra`. We belt-and-
    braces it.
    """
    try:
        # Strip request body
        req = event.get("request") or {}
        if "data" in req:
            req["data"] = "<redacted>"
        for h in ("Authorization", "X-Admin", "X-Agent-Secret"):
            if "headers" in req and h in req["headers"]:
                req["headers"][h] = "<redacted>"
        # Strip extra
        extra = event.get("extra") or {}
        for k in list(extra.keys()):
            if k.lower() in _PII_KEYS:
                extra[k] = "<redacted>"
        # Strip breadcrumbs that look like payloads
        for crumb in event.get("breadcrumbs", {}).get("values", []) or []:
            data = crumb.get("data") or {}
            for k in list(data.keys()):
                if k.lower() in _PII_KEYS:
                    data[k] = "<redacted>"
    except Exception:  # noqa: BLE001
        pass
    return event


def init(force: bool = False) -> bool:
    """Initialize Sentry for the API. Returns True if a real DSN was wired up.

    Safe to call multiple times. If no DSN is set we register tags for noop
    breadcrumbs so the rest of the codebase can call `tag_*` freely.
    """
    global _initialized
    if _initialized and not force:
        return bool(sentry_sdk.Hub.current.client and sentry_sdk.Hub.current.client.dsn)

    settings = get_settings()
    dsn = os.environ.get("SENTRY_DSN_API") or settings.SENTRY_DSN
    env = os.environ.get("ENVIRONMENT", "dev")

    if dsn:
        sentry_sdk.init(
            dsn=dsn,
            integrations=[FastApiIntegration(), StarletteIntegration()],
            traces_sample_rate=0.1,
            environment=env,
            release=f"quill-api@{__version__}",
            send_default_pii=False,
            before_send=_scrub,
        )
        log.info("sentry initialized for service=api env=%s", env)
    else:
        # No DSN — install scope tags anyway so future events (if init'd
        # later) carry the right service identity, and so `tag_*` works.
        log.info("sentry DSN missing — service=api running without remote reporting")

    with sentry_sdk.configure_scope() as scope:
        scope.set_tag("service", "api")
        scope.set_tag("environment", env)
        scope.set_tag("release", f"quill-api@{__version__}")

    _initialized = True
    return bool(dsn)


def tag_request(request_id: str | None = None) -> None:
    if not request_id:
        return
    with sentry_sdk.configure_scope() as scope:
        scope.set_tag("request_id", request_id)


def tag_approval(approval_id: str | None = None) -> None:
    if not approval_id:
        return
    with sentry_sdk.configure_scope() as scope:
        scope.set_tag("approval_id", approval_id)


def tag_user(user_id: str | None = None) -> None:
    if not user_id:
        return
    with sentry_sdk.configure_scope() as scope:
        scope.set_user({"id": user_id})


def tag_agent(agent_id: str | None = None) -> None:
    if not agent_id:
        return
    with sentry_sdk.configure_scope() as scope:
        scope.set_tag("agent_id", agent_id)


def capture_message(msg: str, level: str = "info", **tags: Any) -> str | None:
    """Manual capture with optional tags. Returns the event id when available."""
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
