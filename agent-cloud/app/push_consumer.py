"""Proactive-push consumer — closes the MIGRATION.md §3.1 gap.

Subscribes to the inline event bus for `agent.response` events that carry
a `payload.channel_target`, then immediately sends the reply text via the
appropriate channel adapter (Telegram / Google Chat).

This closes the "scheduled turn produces a reply but nothing pushes it"
gap: previously, replies from scheduled turns landed silently in the session
and only became visible on the user's next web-chat message.  With this
consumer running in the lifespan, any agent.response event with a
channel_target is delivered in real time.

Event shape expected (type=agent.response):
    {
        "payload": {
            "text": "Good morning!  Here is your briefing…",
            "channel_target": {
                "platform": "telegram",       # or "googlechat"
                "chat_id": "1234567890"
            }
        }
    }

Wiring: started/stopped inside the FastAPI lifespan in app/api.py.
Bus support: works with InlineBus (local/dev/tests) which has subscribe/
unsubscribe.  PubSubBus does not expose an in-process subscribe hook — in
that deployment, a separate Cloud Run service would consume the subscription;
the push consumer is intentionally a no-op for PubSubBus.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app import channels as channels_mod
from app.events import InlineBus, get_bus

log = logging.getLogger("agentcloud.push_consumer")


class ProactivePushConsumer:
    """Subscribe to the inline event bus and forward channel-targeted replies.

    Lifecycle: call `await start()` once (registers the callback on the bus)
    and `await stop()` to deregister.  Safe to start/stop repeatedly; the
    callback is idempotent (only one registration at a time).
    """

    def __init__(self) -> None:
        self._registered = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Register the event callback on the active bus (InlineBus only)."""
        bus = get_bus()
        if isinstance(bus, InlineBus):
            bus.subscribe(self._handle_event)
            self._registered = True
            log.info("proactive push consumer started (inline bus)")
        else:
            # PubSubBus: no in-process subscribe hook.  A dedicated Cloud Run
            # subscription consumer handles delivery in that deployment.
            log.info(
                "proactive push consumer: bus=%s has no subscribe hook — "
                "no-op (a separate subscription consumer handles PubSub delivery)",
                bus.name,
            )

    async def stop(self) -> None:
        """Deregister the event callback from the active bus."""
        if not self._registered:
            return
        bus = get_bus()
        if isinstance(bus, InlineBus):
            bus.unsubscribe(self._handle_event)
            self._registered = False
            log.info("proactive push consumer stopped")

    # ------------------------------------------------------------------
    # Callback
    # ------------------------------------------------------------------

    def _handle_event(self, event: dict[str, Any]) -> Any:
        """Dispatch an agent.response event to the appropriate channel.

        The callback is registered as a plain callable on InlineBus; it may
        return a coroutine, which InlineBus awaits automatically.
        """
        if event.get("type") != "agent.response":
            return None  # not our event type; ignore
        payload = event.get("payload") or {}
        channel_target = payload.get("channel_target")
        if not channel_target or not isinstance(channel_target, dict):
            return None  # no channel target; nothing to push
        return self._push(event, payload, channel_target)

    async def _push(
        self,
        event: dict[str, Any],
        payload: dict[str, Any],
        channel_target: dict[str, Any],
    ) -> None:
        platform = (channel_target.get("platform") or "").lower()
        chat_id = str(channel_target.get("chat_id") or "")
        text = str(payload.get("text") or "")

        if not platform or not chat_id or not text:
            log.warning(
                "push_consumer: agent.response missing platform/chat_id/text "
                "(event_id=%s)",
                event.get("event_id"),
            )
            return

        adapter = channels_mod.get_adapter(platform)
        if adapter is None:
            log.warning(
                "push_consumer: unknown platform %r (event_id=%s)",
                platform,
                event.get("event_id"),
            )
            return

        result = await adapter.send(chat_id, text)
        if result.ok:
            log.info(
                "push_consumer: delivered agent.response → %s chat_id=%s (event_id=%s)",
                platform,
                chat_id,
                event.get("event_id"),
            )
        else:
            log.warning(
                "push_consumer: send failed platform=%s chat_id=%s detail=%s (event_id=%s)",
                platform,
                chat_id,
                result.detail,
                event.get("event_id"),
            )
