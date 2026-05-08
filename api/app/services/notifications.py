"""Notifications abstraction.

A uniform interface so callers (approvals service, SLA watcher, admin endpoints,
the Daily Brief job) don't care whether we're using Telegram, SMS, or email.

For Sprint 2.4 only Telegram is a live backend; SMS (Twilio) and email are
stubs that log + return a fake ack so we can flip them on later without
rewriting callers.

Design rules:
  - Every backend method is async.
  - Backends never raise — they return a `NotifyResult` with `ok` + `detail`.
    Callers can choose to alert on `ok=False`, but a bad chat ID must not
    take down a critical write.
  - PII redaction: messages are passed through, but we never auto-include
    approval payloads. The caller is responsible for choosing what's safe to
    surface (already a hard rule across the platform).
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

import httpx

from app.services import sentry as sentry_svc

log = logging.getLogger("quill.notifications")


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------
@dataclass
class NotifyResult:
    ok: bool
    backend: str
    detail: str | None = None
    response: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Sprint-4 fix #4: at-least-once delivery helper
#
# Used by callers that POST to ephemeral or flaky endpoints (e.g. the bot's
# heartbeat to /v1/admin/scheduler/jobs/heartbeat). The helper retries up to
# `max_attempts` times with exponential backoff (1s, 2s, 4s, 8s, 16s by
# default), jitter applied, and on final failure logs a Sentry breadcrumb
# without raising — the heartbeat is non-critical so a hard fail must not
# block the scheduler loop.
# ---------------------------------------------------------------------------
T = TypeVar("T")

# Anything that quacks like a transient failure. We treat httpx network errors
# AND 5xx responses as retryable.
_RETRYABLE_HTTPX = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadError,
    httpx.ReadTimeout,
    httpx.WriteError,
    httpx.WriteTimeout,
    httpx.RemoteProtocolError,
    httpx.PoolTimeout,
)


async def with_retry(
    func: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 16.0,
    sentry_event: str | None = None,
    label: str = "call",
    extra_retry_predicate: Callable[[BaseException], bool] | None = None,
) -> tuple[bool, T | None, BaseException | None]:
    """Run an async no-arg callable with at-least-once retry semantics.

    Returns ``(ok, value, last_exc)``. ``ok=True`` means a success on some
    attempt; ``ok=False`` means all attempts failed and Sentry was notified.
    Never raises.
    """
    delay = base_delay
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            value = await func()
            return True, value, None
        except BaseException as exc:  # noqa: BLE001
            last_exc = exc
            retryable = isinstance(exc, _RETRYABLE_HTTPX) or (
                isinstance(exc, httpx.HTTPStatusError)
                and 500 <= exc.response.status_code < 600
            )
            if extra_retry_predicate is not None:
                retryable = retryable or extra_retry_predicate(exc)
            log.warning(
                "%s attempt %d/%d failed: %s%s",
                label,
                attempt,
                max_attempts,
                exc,
                " (retryable)" if retryable else "",
            )
            if not retryable or attempt >= max_attempts:
                break
            jitter = random.uniform(0, delay * 0.25)
            await asyncio.sleep(min(max_delay, delay) + jitter)
            delay = min(max_delay, delay * 2)

    sentry_svc.capture_message(
        sentry_event or f"{label}_final_failure",
        level="error",
        attempts=max_attempts,
        last_error=str(last_exc) if last_exc else "unknown",
    )
    return False, None, last_exc


# ---------------------------------------------------------------------------
# Backend protocol
# ---------------------------------------------------------------------------
class NotificationBackend(Protocol):
    name: str

    async def send(self, recipient: str, text: str, **kwargs: Any) -> NotifyResult: ...


# ---------------------------------------------------------------------------
# Telegram backend (HTTP Bot API — does not require the bot service to be running)
# ---------------------------------------------------------------------------
class TelegramBackend:
    name = "telegram"

    def __init__(
        self,
        token: str | None = None,
        *,
        timeout: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @property
    def configured(self) -> bool:
        return bool(self._token)

    async def send(
        self,
        recipient: str,
        text: str,
        *,
        parse_mode: str = "Markdown",
        disable_notification: bool = False,
        **_: Any,
    ) -> NotifyResult:
        if recipient.startswith("fake") or recipient == "test":
            # Test affordance: pretend to deliver but never hit the real API.
            # Honored even when no token is configured (so /test_telegram?chat_id=fake
            # works in dev without TELEGRAM_BOT_TOKEN).
            log.info("telegram fake-send → chat_id=%s text=%r", recipient, text[:60])
            return NotifyResult(ok=True, backend=self.name, detail="fake")
        if not self._token:
            log.warning("telegram backend not configured (TELEGRAM_BOT_TOKEN missing)")
            return NotifyResult(ok=False, backend=self.name, detail="missing_token")

        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        body = {
            "chat_id": recipient,
            "text": text,
            "parse_mode": parse_mode,
            "disable_notification": disable_notification,
        }
        try:
            resp = await self._client.post(url, json=body)
            data = resp.json() if resp.headers.get("content-type", "").startswith(
                "application/json"
            ) else {}
            if resp.status_code >= 400 or not data.get("ok", False):
                log.error("telegram send failed: %s %s", resp.status_code, resp.text[:300])
                sentry_svc.capture_message(
                    "telegram_send_failed",
                    level="error",
                    chat_id=recipient,
                    status=resp.status_code,
                )
                return NotifyResult(
                    ok=False, backend=self.name, detail=f"http_{resp.status_code}"
                )
            return NotifyResult(ok=True, backend=self.name, response=data)
        except httpx.HTTPError as e:
            log.error("telegram send exception: %s", e)
            sentry_svc.capture_exception(e, chat_id=recipient)
            return NotifyResult(ok=False, backend=self.name, detail=str(e))


# ---------------------------------------------------------------------------
# Stub backends — log + return success so future wiring is a no-op
# ---------------------------------------------------------------------------
class TwilioStubBackend:
    name = "twilio_sms"

    async def send(self, recipient: str, text: str, **_: Any) -> NotifyResult:
        log.info("[STUB sms] to=%s text=%r", recipient, text[:80])
        return NotifyResult(ok=True, backend=self.name, detail="stub")


class EmailStubBackend:
    name = "email"

    async def send(self, recipient: str, text: str, **_: Any) -> NotifyResult:
        log.info("[STUB email] to=%s text=%r", recipient, text[:80])
        return NotifyResult(ok=True, backend=self.name, detail="stub")


# ---------------------------------------------------------------------------
# Drive uploader (gog CLI shell-out — used by the Daily Brief job)
# ---------------------------------------------------------------------------
async def drive_upload(path: str, content: str, *, mime: str = "text/markdown") -> NotifyResult:
    """Upload a string blob to Google Drive at `path` using the gog CLI.

    `path` is treated as a Drive-side path (e.g. `/Quill/briefs/2026-05-08-daily.md`).
    For environments where gog isn't on PATH we degrade to a local-file write
    under /tmp/quill-drive/<path> so the caller can still verify behavior.
    """
    import tempfile

    # 1) write the content to a temp file (gog prefers paths)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    )
    tmp.write(content)
    tmp.close()
    local_path = tmp.name

    # 2) try gog; fall back to a /tmp mirror
    try:
        proc = await asyncio.create_subprocess_exec(
            "gog", "drive", "upload", local_path, path, "--mime", mime,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode == 0:
            return NotifyResult(
                ok=True, backend="drive", detail=out.decode().strip() or "uploaded"
            )
        log.warning("gog upload failed (rc=%s): %s", proc.returncode, err.decode()[:300])
    except FileNotFoundError:
        log.info("gog CLI not found on PATH — falling back to local mirror")
    except Exception as e:  # noqa: BLE001
        log.warning("gog upload exception: %s", e)

    # 3) fallback: write under /tmp/quill-drive
    import shutil
    from pathlib import Path

    fallback_root = Path("/tmp/quill-drive")
    fallback_path = fallback_root / path.lstrip("/")
    fallback_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(local_path, fallback_path)
    return NotifyResult(
        ok=True, backend="drive", detail=f"local-fallback:{fallback_path}"
    )


# ---------------------------------------------------------------------------
# Notifier — tiny façade
# ---------------------------------------------------------------------------
class Notifier:
    """Single entry point used by API code.

    Usage:
        from app.services.notifications import notifier
        await notifier.telegram_message(chat_id, "hello", parse_mode="Markdown")
        await notifier.sentry_event("error", "thing failed", approval_id="...")
        await notifier.drive_upload("/Quill/briefs/x.md", text)
    """

    def __init__(
        self,
        telegram: TelegramBackend | None = None,
        sms: TwilioStubBackend | None = None,
        email: EmailStubBackend | None = None,
    ) -> None:
        self.telegram = telegram or TelegramBackend()
        self.sms = sms or TwilioStubBackend()
        self.email = email or EmailStubBackend()

    async def telegram_message(
        self,
        chat_id: str | int,
        text: str,
        *,
        parse_mode: str = "Markdown",
        silent: bool = False,
    ) -> NotifyResult:
        return await self.telegram.send(
            str(chat_id), text, parse_mode=parse_mode, disable_notification=silent
        )

    async def sms_message(self, phone: str, text: str) -> NotifyResult:
        return await self.sms.send(phone, text)

    async def email_message(self, address: str, text: str) -> NotifyResult:
        return await self.email.send(address, text)

    async def sentry_event(
        self,
        level: str,
        message: str,
        **tags: Any,
    ) -> NotifyResult:
        eid = sentry_svc.capture_message(message, level=level, **tags)
        return NotifyResult(
            ok=True, backend="sentry", detail=eid or "no-dsn"
        )

    async def drive_upload(self, path: str, content: str, *, mime: str = "text/markdown") -> NotifyResult:
        return await drive_upload(path, content, mime=mime)


# Module-level singleton — most callers just `from ... import notifier`.
notifier = Notifier()
