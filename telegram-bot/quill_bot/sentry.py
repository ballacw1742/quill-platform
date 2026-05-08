"""Bot-side Sentry init (Sprint 2.4)."""

from __future__ import annotations

import logging
import os
from typing import Any

import sentry_sdk

log = logging.getLogger("quill.bot.sentry")

_initialized = False

_PII_KEYS = frozenset(
    {"payload", "token", "secret", "authorization", "private_key",
     "telegram_bot_token", "deeplink_signing_secret"}
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
    except Exception:  # noqa: BLE001
        pass
    return event


def init(dsn: str = "", environment: str = "dev", force: bool = False) -> bool:
    """Initialize Sentry for the bot. Idempotent + safe with no DSN."""
    global _initialized
    if _initialized and not force:
        return bool(sentry_sdk.Hub.current.client and sentry_sdk.Hub.current.client.dsn)

    dsn = dsn or os.environ.get("SENTRY_DSN_BOT") or os.environ.get("SENTRY_DSN", "")
    env = environment or os.environ.get("ENVIRONMENT", "dev")

    if dsn:
        try:
            from quill_bot import __version__
        except Exception:  # noqa: BLE001
            __version__ = "0.0.0"
        sentry_sdk.init(
            dsn=dsn,
            traces_sample_rate=0.1,
            environment=env,
            release=f"quill-bot@{__version__}",
            send_default_pii=False,
            before_send=_scrub,
        )
        log.info("sentry initialized for service=bot env=%s", env)
    else:
        log.info("sentry DSN missing — service=bot running without remote reporting")

    with sentry_sdk.configure_scope() as scope:
        scope.set_tag("service", "bot")
        scope.set_tag("environment", env)

    _initialized = True
    return bool(dsn)


def tag_user(user_id: str | None = None, chat_id: str | int | None = None) -> None:
    with sentry_sdk.configure_scope() as scope:
        if user_id:
            scope.set_user({"id": user_id})
        if chat_id is not None:
            scope.set_tag("chat_id", str(chat_id))


def tag_approval(approval_id: str | None = None) -> None:
    if not approval_id:
        return
    with sentry_sdk.configure_scope() as scope:
        scope.set_tag("approval_id", approval_id)


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
