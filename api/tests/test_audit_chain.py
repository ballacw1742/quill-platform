"""Audit chain integrity — corrupt a row, verify detection."""

from __future__ import annotations

from app.models import AuditLogEntry
from sqlalchemy import select

from tests.conftest import agent_h

SAMPLE = {
    "agent_id": "rfi-triage",
    "workflow": "rfi.classify",
    "lane": 2,
    "agent_confidence": 0.7,
    "payload": {"rfi_id": "RFI-A-1"},
    "source_artifacts": [{"kind": "rfi", "ref": "RFI-A-1"}],
    "citations": [{"source_type": "procore_rfi", "source_id": "RFI-A-1"}],
}


async def test_chain_detects_tamper(client, session_maker):
    r = await client.post("/v1/approvals", json=SAMPLE, headers=agent_h())
    aid = r.json()["id"]

    # First confirm chain ok
    r = await client.get(f"/v1/audit/verify/{aid}")
    assert r.json()["ok"] is True

    # Tamper: rewrite payload of the audit row
    async with session_maker() as s:
        res = await s.execute(
            select(AuditLogEntry).where(AuditLogEntry.approval_item_id == aid)
        )
        entry = res.scalars().first()
        entry.payload = {**entry.payload, "tampered": True}
        await s.commit()

    r = await client.get(f"/v1/audit/verify/{aid}")
    body = r.json()
    assert body["ok"] is False
    assert any("hash_mismatch" in f for f in body["failures"])
