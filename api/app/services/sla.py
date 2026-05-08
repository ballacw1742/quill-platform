"""Background SLA watcher. Wakes every 60s, fires events on breach."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app import db as db_module
from app.enums import ApprovalStatus
from app.models import ApprovalItem
from app.services import audit as audit_svc
from app.services.realtime import broadcaster

log = logging.getLogger("quill.sla")

POLL_SECONDS = 60


async def _scan_once() -> int:
    """One pass: find pending items past sla_due_at that haven't fired yet."""
    fired = 0
    async with db_module.SessionLocal() as session:
        now = datetime.now(UTC)
        res = await session.execute(
            select(ApprovalItem).where(
                ApprovalItem.status == ApprovalStatus.PENDING.value,
                ApprovalItem.sla_due_at.is_not(None),
                ApprovalItem.sla_due_at < now,
            )
        )
        items = res.scalars().all()
        for item in items:
            # Idempotency: tag a payload event each scan but only fire if not previously fired
            # (we look for an existing breach audit row).
            from app.models import AuditLogEntry

            existing = await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.approval_item_id == item.id,
                    AuditLogEntry.event_type == "approval.sla_breach",
                )
            )
            if existing.scalars().first() is not None:
                continue

            entry = await audit_svc.record_event(
                session,
                event_type="approval.sla_breach",
                actor="system:sla_watcher",
                approval_item_id=item.id,
                payload={
                    "sla_due_at": item.sla_due_at.isoformat() if item.sla_due_at else None,
                    "lane": item.lane,
                    "priority": item.priority,
                },
            )
            item.prev_audit_hash = item.audit_hash
            item.audit_hash = entry.hash
            await session.commit()
            await broadcaster.publish(
                {
                    "type": "approval.sla_breach",
                    "id": item.id,
                    "lane": item.lane,
                    "priority": item.priority,
                }
            )
            log.warning("SLA breach: %s lane=%s priority=%s", item.id, item.lane, item.priority)
            fired += 1
    return fired


async def run_forever() -> None:
    log.info("SLA watcher starting (poll=%ss)", POLL_SECONDS)
    while True:
        try:
            await _scan_once()
        except Exception:  # noqa: BLE001
            log.exception("sla scan failed")
        await asyncio.sleep(POLL_SECONDS)
