"""Sprint 2.3 — chain verification tests.

Covers:
  * full chain on a clean DB → ok
  * tamper a Postgres entry → postgres_drift detected
  * tamper a B2 (local) entry → b2_drift detected
  * delete a mirror entry → missing detected
  * per-approval scope works
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from app.config import get_settings
from app.models import AuditChainVerification, AuditLogEntry
from app.services import audit_verify as verify_svc
from app.services.audit_mirror import get_mirror, reset_mirror_for_tests
from sqlalchemy import select

from tests.conftest import agent_h

SAMPLE = {
    "agent_id": "rfi-triage",
    "workflow": "rfi.classify",
    "lane": 2,
    "agent_confidence": 0.7,
    "payload": {"rfi_id": "RFI-VERIFY-1"},
    "source_artifacts": [{"kind": "rfi", "ref": "RFI-VERIFY-1"}],
    "citations": [{"source_type": "procore_rfi", "source_id": "RFI-VERIFY-1"}],
}


@pytest.fixture(autouse=True)
def isolated_mirror(tmp_path: Path, monkeypatch):
    """Each verify test gets its own scratch mirror dir + fresh singleton.

    Also clears any stale freeze flag.
    """
    s = get_settings()
    monkeypatch.setattr(s, "B2_KEY_ID", "")
    monkeypatch.setattr(s, "B2_APPLICATION_KEY", "")
    monkeypatch.setattr(s, "AUDIT_MIRROR_LOCAL_PATH", str(tmp_path / "verify_mirror"))
    monkeypatch.setattr(s, "AUDIT_FREEZE_FLAG_PATH", str(tmp_path / "freeze.flag"))
    reset_mirror_for_tests()
    yield
    reset_mirror_for_tests()
    # Belt-and-braces: ensure no freeze flag leaks across tests.
    flag = s.AUDIT_FREEZE_FLAG_PATH
    if flag and os.path.exists(flag):
        try:
            os.remove(flag)
        except OSError:
            pass


async def _drain_mirror_to_disk():
    mirror = get_mirror()
    deadline = asyncio.get_event_loop().time() + 2.0
    while asyncio.get_event_loop().time() < deadline and mirror.get_status()["queue_depth"] > 0:
        await asyncio.sleep(0.02)
    if mirror.get_status()["queue_depth"] > 0:
        await mirror.drain()


async def test_full_chain_clean_db_returns_ok(client, session_maker):
    r = await client.post("/v1/approvals", json=SAMPLE, headers=agent_h())
    assert r.status_code == 201, r.text
    await _drain_mirror_to_disk()

    async with session_maker() as s:
        result = await verify_svc.verify_full_chain(s, triggered_by="test")
    assert result["ok"], result
    assert result["result"] == "ok"
    assert result["chain_length_postgres"] >= 1
    assert result["chain_length_mirror"] == result["chain_length_postgres"]


async def test_tamper_postgres_detects_drift(client, session_maker):
    r = await client.post("/v1/approvals", json=SAMPLE, headers=agent_h())
    aid = r.json()["id"]
    await _drain_mirror_to_disk()

    async with session_maker() as s:
        res = await s.execute(
            select(AuditLogEntry).where(AuditLogEntry.approval_item_id == aid)
        )
        entry = res.scalars().first()
        entry.payload = {**entry.payload, "tampered": "yes"}
        await s.commit()

    async with session_maker() as s:
        result = await verify_svc.verify_full_chain(s, triggered_by="test")
    assert not result["ok"]
    assert result["result"] == "postgres_drift"
    failures = result["details"]["postgres_failures"]
    assert any(f["kind"] == "hash_mismatch" and f["entry_id"] == entry.id for f in failures)
    # Freeze flag was touched
    assert os.path.exists(get_settings().AUDIT_FREEZE_FLAG_PATH)


async def test_tamper_mirror_detects_b2_drift(client, session_maker, tmp_path):
    r = await client.post("/v1/approvals", json=SAMPLE, headers=agent_h())
    aid = r.json()["id"]
    await _drain_mirror_to_disk()

    # Find a mirror file for this approval and corrupt its hash field
    root = Path(get_settings().AUDIT_MIRROR_LOCAL_PATH)
    files = list(root.rglob(f"*/{aid}/*.json"))
    assert files
    corrupted = files[0]
    doc = json.loads(corrupted.read_text())
    doc["hash"] = "0" * 64  # bogus hash
    corrupted.write_text(json.dumps(doc, sort_keys=True, separators=(",", ":")))

    async with session_maker() as s:
        result = await verify_svc.verify_full_chain(s, triggered_by="test")

    assert not result["ok"]
    # Could be b2_drift OR mismatch depending on which way the diff lands;
    # in our implementation hash field mismatch always reports b2_drift first.
    assert result["result"] == "b2_drift"
    assert any(
        f["kind"] in ("b2_hash_mismatch", "b2_body_drift")
        for f in result["details"]["b2_failures"]
    )


async def test_missing_mirror_entry_detected(client, session_maker):
    r = await client.post("/v1/approvals", json=SAMPLE, headers=agent_h())
    aid = r.json()["id"]
    await _drain_mirror_to_disk()

    root = Path(get_settings().AUDIT_MIRROR_LOCAL_PATH)
    files = list(root.rglob(f"*/{aid}/*.json"))
    assert files
    files[0].unlink()  # delete one mirrored entry

    async with session_maker() as s:
        result = await verify_svc.verify_full_chain(s, triggered_by="test")
    assert not result["ok"]
    assert result["result"] == "missing"
    assert result["details"]["missing_in_mirror"]


async def test_per_approval_scope(client, session_maker):
    r1 = await client.post("/v1/approvals", json=SAMPLE, headers=agent_h())
    aid1 = r1.json()["id"]
    other = {**SAMPLE, "payload": {"rfi_id": "RFI-OTHER"}}
    await client.post("/v1/approvals", json=other, headers=agent_h())
    await _drain_mirror_to_disk()

    async with session_maker() as s:
        result = await verify_svc.verify_per_approval(s, aid1, triggered_by="test")
    assert result["ok"], result
    assert result["scope"] == "per_approval"
    assert result["scope_ref"] == aid1
    # Only entries for aid1 counted
    assert result["chain_length_postgres"] >= 1


async def test_verification_row_persisted(client, session_maker):
    await client.post("/v1/approvals", json=SAMPLE, headers=agent_h())
    await _drain_mirror_to_disk()
    async with session_maker() as s:
        await verify_svc.verify_full_chain(s, triggered_by="test")
    async with session_maker() as s:
        rows = (await s.execute(select(AuditChainVerification))).scalars().all()
    assert len(rows) >= 1
    assert all(r.scope == "global" for r in rows)
    assert any(r.triggered_by == "test" for r in rows)


async def test_admin_endpoints_smoke(client, session_maker):
    await client.post("/v1/approvals", json=SAMPLE, headers=agent_h())
    await _drain_mirror_to_disk()

    admin_h = {"X-Admin": os.environ["AGENT_SHARED_SECRET"]}

    s_r = await client.get("/v1/admin/audit/mirror_status", headers=admin_h)
    assert s_r.status_code == 200
    assert s_r.json()["mode"] == "local"

    v_r = await client.post("/v1/admin/audit/verify_now", json={}, headers=admin_h)
    assert v_r.status_code == 200, v_r.text
    job_id = v_r.json()["job_id"]

    j_r = await client.get(f"/v1/admin/audit/verify_job/{job_id}", headers=admin_h)
    assert j_r.status_code == 200
    assert j_r.json()["status"] == "done"
    assert j_r.json()["result"]["ok"] is True

    list_r = await client.get(
        "/v1/admin/audit/verifications/recent?limit=5", headers=admin_h
    )
    assert list_r.status_code == 200
    assert isinstance(list_r.json(), list)
    assert len(list_r.json()) >= 1
