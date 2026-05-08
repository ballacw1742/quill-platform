"""SLA timer behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.enums import Lane, Priority
from app.models import ApprovalItem, AuditLogEntry
from app.services.approvals import compute_sla_due
from app.services.sla import _scan_once
from sqlalchemy import select


def test_compute_sla_lane_defaults():
    now = datetime.now(UTC)
    lane2 = compute_sla_due(Lane.SINGLE.value, Priority.NORMAL.value, now)
    assert (lane2 - now) == timedelta(hours=8)
    lane3 = compute_sla_due(Lane.DUAL.value, Priority.NORMAL.value, now)
    assert (lane3 - now) == timedelta(hours=24)
    crit = compute_sla_due(Lane.SINGLE.value, Priority.CRITICAL_PATH.value, now)
    assert (crit - now) == timedelta(hours=4)


async def test_sla_breach_fires(client, session_maker):
    # `client` fixture already monkeypatches db.SessionLocal to session_maker.

    # Create an approval and rewrite sla_due_at to the past
    payload = {
        "agent_id": "rfi-triage",
        "workflow": "rfi.classify",
        "lane": 2,
        "agent_confidence": 0.5,
        "payload": {"rfi_id": "RFI-S-1"},
        "source_artifacts": [{"kind": "rfi", "ref": "x"}],
        "citations": [{"source_type": "procore_rfi", "source_id": "x"}],
    }
    r = await client.post(
        "/v1/approvals", json=payload, headers={"X-Agent-Secret": "test-agent-secret"}
    )
    aid = r.json()["id"]

    async with session_maker() as s:
        item = await s.get(ApprovalItem, aid)
        item.sla_due_at = datetime.now(UTC) - timedelta(hours=1)
        await s.commit()

    fired = await _scan_once()
    assert fired == 1

    # Idempotent — second scan does nothing
    again = await _scan_once()
    assert again == 0

    async with session_maker() as s:
        breach = await s.execute(
            select(AuditLogEntry).where(
                AuditLogEntry.approval_item_id == aid,
                AuditLogEntry.event_type == "approval.sla_breach",
            )
        )
        assert breach.scalars().first() is not None
