"""Event bus + durable event records (contract: agent-cloud/EVENTS.md).

Two halves, used together:
  - `record_events(db, events)` writes the durable agentcloud_events rows
    inside an existing tenant transaction (tx2, alongside message/job
    persistence — the table is the source of truth).
  - `emit(events)` publishes to the configured bus AFTER the tx commits.
    Publish is best-effort by contract: any bus error is logged and
    swallowed — a user turn never blocks or fails on the bus.

EVENT_BUS is config-gated like MODEL_PROVIDER:
  - "inline" (default): in-process dispatch to registered subscribers.
    Used by local/dev/tests; no network.
  - "pubsub": google-cloud-pubsub publisher to EVENT_TOPIC. The
    subscription-side retry + dead-letter policy is documented in EVENTS.md
    (max 5 delivery attempts → agentcloud-events-deadletter).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import EventRow

log = logging.getLogger("agentcloud.events")

EVENT_TYPES = (
    "turn.completed",
    "tool.executed",
    "budget.exceeded",
    "subagent.started",
    "subagent.completed",
    "subagent.failed",
    "schedule.fired",
    "schedule.failed",
    "approval.requested",
    "approval.resolved",
    "rate_limit.exceeded",  # B2 (LIMITS.md §3)
    "agent.updated",  # Phase C (AGENT_BUILDER.md §9)
    "channel.linked",  # Phase D (CHANNELS.md §8)
    "channel.message",  # Phase D (CHANNELS.md §8)
    # Phase §9 Wave 2 additions
    "agent.response",   # scheduled turn reply destined for a channel (MIGRATION.md §3.1)
    "email.send_queued",  # approval-gated email proposal queued (MIGRATION.md §3.3)
)


def make_event(
    *,
    tenant_id: str,
    type: str,
    payload: dict[str, Any],
    agent_id: str = "",
    session_id: uuid.UUID | str | None = None,
    attempt: int = 1,
) -> dict[str, Any]:
    """Build one EVENTS.md envelope. Types outside the contract are refused."""
    if type not in EVENT_TYPES:
        raise ValueError(f"event type {type!r} is not in the EVENTS.md contract")
    return {
        "event_id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "session_id": str(session_id) if session_id else None,
        "type": type,
        "ts": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
        "attempt": attempt,
    }


def record_events(db: AsyncSession, events: list[dict[str, Any]]) -> None:
    """Add durable agentcloud_events rows to an open tenant transaction."""
    for ev in events:
        db.add(
            EventRow(
                event_id=uuid.UUID(ev["event_id"]),
                tenant_id=ev["tenant_id"],
                agent_id=ev.get("agent_id") or "",
                session_id=uuid.UUID(ev["session_id"]) if ev.get("session_id") else None,
                type=ev["type"],
                payload=ev.get("payload") or {},
                attempt=ev.get("attempt", 1),
            )
        )


class InlineBus:
    """In-process dispatch (EVENT_BUS=inline). Subscribers are sync/async
    callables; every published envelope is also kept in `.published` so
    tests/dev tooling can assert against the contract."""

    name = "inline"

    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []
        self._subscribers: list[Callable[[dict[str, Any]], Any]] = []

    def subscribe(self, fn: Callable[[dict[str, Any]], Any]) -> None:
        self._subscribers.append(fn)

    def unsubscribe(self, fn: Callable[[dict[str, Any]], Any]) -> None:
        """Remove a previously registered subscriber (no-op if not found)."""
        try:
            self._subscribers.remove(fn)
        except ValueError:
            pass

    async def publish(self, event: dict[str, Any]) -> None:
        self.published.append(event)
        for fn in self._subscribers:
            res = fn(event)
            if asyncio.iscoroutine(res):
                await res


class PubSubBus:
    """google-cloud-pubsub publisher (EVENT_BUS=pubsub).

    Message data = the JSON envelope; attributes mirror tenant_id/type for
    subscription filters; ordering_key = session_id (or tenant_id) per
    EVENTS.md. The client is created lazily so the dependency is only
    required when this backend is selected.
    """

    name = "pubsub"

    def __init__(self, client_factory: Callable[[], Any] | None = None) -> None:
        self._client_factory = client_factory
        self._client: Any = None

    def _get_client(self):
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory()
            else:  # pragma: no cover — exercised in prod only
                from google.cloud import pubsub_v1  # noqa: PLC0415

                self._client = pubsub_v1.PublisherClient(
                    publisher_options=pubsub_v1.types.PublisherOptions(
                        enable_message_ordering=True
                    )
                )
        return self._client

    async def publish(self, event: dict[str, Any]) -> None:
        s = get_settings()
        client = self._get_client()
        topic = f"projects/{s.PUBSUB_PROJECT}/topics/{s.EVENT_TOPIC}"
        data = json.dumps(event, default=str).encode()
        ordering_key = event.get("session_id") or event["tenant_id"]
        future = client.publish(
            topic,
            data,
            tenant_id=event["tenant_id"],
            type=event["type"],
            ordering_key=ordering_key,
        )
        # Bounded wait off the event loop; never blocks the turn beyond this.
        await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(None, future.result),
            timeout=s.EVENT_PUBLISH_TIMEOUT_SECONDS,
        )


_bus: InlineBus | PubSubBus | None = None


def get_bus() -> InlineBus | PubSubBus:
    global _bus
    if _bus is None:
        backend = get_settings().EVENT_BUS
        if backend == "pubsub":
            _bus = PubSubBus()
        elif backend == "inline":
            _bus = InlineBus()
        else:
            raise ValueError(f"unknown EVENT_BUS {backend!r} (inline|pubsub)")
    return _bus


def reset_bus() -> None:
    """Test hook (mirrors provider reset patterns)."""
    global _bus
    _bus = None


async def emit(events: list[dict[str, Any]]) -> None:
    """Best-effort publish. Errors are logged, never raised (EVENTS.md)."""
    if not events:
        return
    try:
        bus = get_bus()
    except Exception:  # noqa: BLE001 — misconfig must not fail a turn
        log.exception("event bus unavailable — events remain in agentcloud_events")
        return
    for ev in events:
        try:
            await bus.publish(ev)
        except Exception:  # noqa: BLE001 — publish is best-effort by contract
            log.exception(
                "event publish failed (event_id=%s type=%s) — durable row is authoritative",
                ev.get("event_id"),
                ev.get("type"),
            )
