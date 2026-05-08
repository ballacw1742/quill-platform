"""Push-notification engine for the bot.

Two streams:
  1. WebSocket /ws/approvals — live notifications for new + state-changed items.
  2. Polling /v1/admin/health every config.poll_interval_health_s — fleet health.

Notification rules (Sprint 2.4):
  - New Lane 2 item → silent push
  - New Lane 3 item → push with sound
  - Critical-path-flagged → immediate, high priority
  - Safety-flagged → immediate, high priority
  - Lane 2 > 4h → reminder (handled by scheduler.py, not here)
  - Lane 2 > 8h → escalation reminder (scheduler.py)
  - Lane 3 > 12h → escalation reminder (scheduler.py)

This module is structured so the WebSocket consumer is a tiny, restartable
coroutine — it dies on connection drop and the supervisor reconnects with
exponential backoff.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from quill_bot.api_client import QuillAPIClient, QuillAPIError
from quill_bot.config import BotConfig

log = logging.getLogger("quill.bot.notifier")


# Type for the bot's send_message function — chat_id, text, silent
SendFn = Callable[[str | int, str, bool], Awaitable[None]]


@dataclass
class Notification:
    chat_id: str | int
    text: str
    silent: bool = False


# ---------------------------------------------------------------------------
# Event classification
# ---------------------------------------------------------------------------
def classify_event(event: dict[str, Any]) -> Notification | None:
    """Decide whether and how to notify on a single WS event.

    The API broadcasts JSON events like:
        {"type": "approval.created", "id": "...", "lane": 2, ...}
        {"type": "approval.decided", "id": "...", "decision": "approve"}
        {"type": "approval.sla_breach", "id": "..."}

    Returns None when no notification is needed.
    """
    etype = event.get("type", "")
    item = event.get("item") or event
    short_id = (item.get("id") or "")[:8]
    lane = int(item.get("lane") or 0)
    payload = item.get("payload") or {}
    workflow = item.get("workflow", "?")
    safety = bool(payload.get("safety_critical"))
    crit_path = bool(payload.get("critical_path"))
    priority = item.get("priority", "normal")

    if etype == "approval.created":
        # Lane 1 doesn't notify — it's autopiloted.
        if lane == 1:
            return None
        # Determine push behavior
        force_high = safety or crit_path or priority == "critical"
        prefix = "🚨" if force_high else ("🛎️" if lane == 3 else "📩")
        flags = []
        if safety:
            flags.append("safety")
        if crit_path:
            flags.append("critical-path")
        if priority == "critical":
            flags.append("priority=critical")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        text = (
            f"{prefix} *New Lane {lane} approval*{flag_str}\n"
            f"`{short_id}` — `{workflow}`\n\n"
            f"`/approve {item.get('id')}` · `/reject {item.get('id')} <reason>` · `/edit {item.get('id')}`"
        )
        silent = (lane == 2) and not force_high
        return Notification(chat_id="", text=text, silent=silent)

    if etype == "approval.sla_breach":
        return Notification(
            chat_id="",
            text=f"⏰ *SLA breach* on `{short_id}` — `{workflow}` (Lane {lane})",
            silent=False,
        )

    if etype == "approval.decided":
        decision = item.get("decision", "?")
        emoji = {"approve": "✅", "reject": "❌", "edit": "✏️", "escalate": "⬆️"}.get(
            decision, "ℹ️"
        )
        return Notification(
            chat_id="",
            text=f"{emoji} `{short_id}` — `{decision}` (workflow `{workflow}`)",
            silent=True,
        )

    return None


# ---------------------------------------------------------------------------
# WebSocket consumer
# ---------------------------------------------------------------------------
async def consume_websocket(
    config: BotConfig,
    *,
    target_chat_id: str | int,
    send: SendFn,
    stop_event: asyncio.Event | None = None,
    max_retries: int = 0,  # 0 = retry forever
) -> None:
    """Long-lived coroutine: connect, consume events, push notifications.

    On disconnect, reconnects with exponential backoff (1s, 2s, 4s, … capped at 30s).
    Returns when stop_event is set or max_retries is exhausted.
    """
    try:
        import websockets  # type: ignore
    except ImportError:
        log.error("websockets package not installed — WebSocket consumer disabled")
        return

    backoff = 1.0
    attempt = 0
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            async with websockets.connect(config.quill_ws_url) as ws:
                log.info("ws connected: %s", config.quill_ws_url)
                backoff = 1.0  # reset on success
                async for raw in ws:
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        log.warning("ws: bad JSON: %r", raw[:200])
                        continue
                    notif = classify_event(event)
                    if notif is None:
                        continue
                    notif.chat_id = target_chat_id
                    try:
                        await send(notif.chat_id, notif.text, notif.silent)
                    except Exception as e:  # noqa: BLE001
                        log.exception("send_message failed: %s", e)
        except Exception as e:  # noqa: BLE001
            log.warning("ws disconnected: %s — reconnecting in %.1fs", e, backoff)
            attempt += 1
            if max_retries and attempt >= max_retries:
                return
            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                return
            backoff = min(backoff * 2, 30.0)


# ---------------------------------------------------------------------------
# Health poller
# ---------------------------------------------------------------------------
async def poll_health(
    config: BotConfig,
    api: QuillAPIClient,
    *,
    target_chat_id: str | int,
    send: SendFn,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Poll /v1/admin/health on an interval; fire alerts on regression.

    Tracks last_ok flag in a closure: only re-alerts on transitions
    (ok→fail, audit ok→broken, sla=0→sla>0) to avoid spam.
    """
    last_ok = True
    last_audit = "ok"
    last_sla_breaches = 0

    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            h = await api.health()
            ok = bool(h.get("ok"))
            audit = h.get("audit_chain", "?")
            sla = int(h.get("sla_breaches_open") or 0)

            messages: list[str] = []
            if last_ok and not ok:
                messages.append("🔴 *Quill API unhealthy* — DB or audit chain failure.")
            if last_audit == "ok" and audit == "broken":
                messages.append("🚨 *Audit chain BROKEN.* Investigate immediately.")
            if last_sla_breaches == 0 and sla > 0:
                messages.append(f"⏰ *{sla} SLA breach(es) open.*")
            elif sla > last_sla_breaches:
                messages.append(f"⏰ *SLA breaches climbing:* {last_sla_breaches} → {sla}.")

            for msg in messages:
                try:
                    await send(target_chat_id, msg, False)
                except Exception as e:  # noqa: BLE001
                    log.exception("send_message failed: %s", e)

            last_ok = ok
            last_audit = audit
            last_sla_breaches = sla
        except QuillAPIError as e:
            log.warning("health poll failed: %s", e)
        except Exception as e:  # noqa: BLE001
            log.exception("health poll error: %s", e)

        try:
            await asyncio.sleep(config.poll_interval_health_s)
        except asyncio.CancelledError:
            return
