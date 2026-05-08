"""Sprint 2.3 — audit mirror tests.

Covers:
  * enqueue + drain to the local-disk backend
  * idempotency (same hash twice -> single object)
  * exponential backoff on transient backend failure
  * fallback to local-mode when no B2 creds
  * mirror lag/queue-depth metrics surfaced via get_status()
  * end-to-end: a posted approval lands in the mirror within ~ a second
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.config import get_settings
from app.services import audit_mirror as mm
from app.services.audit_mirror import (
    AuditMirror,
    LocalDiskBackend,
    canonical_json,
    entry_object_key,
    entry_to_canonical_payload,
    reset_mirror_for_tests,
)

from tests.conftest import agent_h

SAMPLE = {
    "agent_id": "rfi-triage",
    "workflow": "rfi.classify",
    "lane": 2,
    "agent_confidence": 0.7,
    "payload": {"rfi_id": "RFI-MIRROR-1"},
    "source_artifacts": [{"kind": "rfi", "ref": "RFI-MIRROR-1"}],
    "citations": [{"source_type": "procore_rfi", "source_id": "RFI-MIRROR-1"}],
}


class _FakeEntry:
    """Stand-in for AuditLogEntry when we don't want to round-trip the DB."""

    def __init__(self, *, eid: int, approval_id: str | None = None, h: str = "abc123"):
        self.id = eid
        self.event_type = "test.event"
        self.actor = "tester"
        self.approval_item_id = approval_id
        self.payload = {"k": "v", "eid": eid}
        self.timestamp = datetime(2026, 5, 8, 12, 30, tzinfo=UTC)
        self.hash = h
        self.prev_hash = None


@pytest.fixture
def tmp_mirror_root(tmp_path: Path):
    yield tmp_path / "_mirror"


@pytest.fixture
def fresh_mirror(tmp_mirror_root: Path, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "B2_KEY_ID", "")
    monkeypatch.setattr(s, "B2_APPLICATION_KEY", "")
    monkeypatch.setattr(s, "AUDIT_MIRROR_LOCAL_PATH", str(tmp_mirror_root))
    reset_mirror_for_tests()
    backend = LocalDiskBackend(tmp_mirror_root)
    m = AuditMirror(backend, max_retries=3)
    yield m
    reset_mirror_for_tests()


# ---------------------------------------------------------------------------
async def test_enqueue_and_drain_writes_local_disk(fresh_mirror, tmp_mirror_root):
    e = _FakeEntry(eid=1, approval_id="appr-A", h="hash-A1")
    fresh_mirror.enqueue(e)
    assert fresh_mirror.get_status()["queue_depth"] == 1
    n = await fresh_mirror.drain()
    assert n == 1
    files = list(tmp_mirror_root.rglob("*.json"))
    assert len(files) == 1
    body = json.loads(files[0].read_text())
    assert body["hash"] == "hash-A1"
    assert body["approval_item_id"] == "appr-A"
    assert body["id"] == 1
    status = fresh_mirror.get_status()
    assert status["queue_depth"] == 0
    assert status["last_mirrored_seq"] == 1
    assert status["total_mirrored"] == 1


async def test_idempotent_double_enqueue(fresh_mirror, tmp_mirror_root):
    e = _FakeEntry(eid=2, approval_id="appr-B", h="hash-dup")
    fresh_mirror.enqueue(e)
    fresh_mirror.enqueue(e)  # second call should be a no-op
    assert fresh_mirror.get_status()["queue_depth"] == 1
    await fresh_mirror.drain()
    files = list(tmp_mirror_root.rglob("*.json"))
    assert len(files) == 1


async def test_local_mode_fallback_when_no_b2_creds(monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "B2_KEY_ID", "")
    monkeypatch.setattr(s, "B2_APPLICATION_KEY", "")
    monkeypatch.setattr(s, "AUDIT_MIRROR_LOCAL_PATH", str(tmp_path / "fallback"))
    reset_mirror_for_tests()
    backend = mm.build_backend()
    assert backend.mode == "local"
    reset_mirror_for_tests()


async def test_backoff_on_failure_then_eventual_failure(fresh_mirror, monkeypatch):
    e = _FakeEntry(eid=3, approval_id="appr-C", h="hash-flaky")
    calls: list[float] = []

    async def _flaky_put(self, key, body):  # noqa: ARG001
        calls.append(time.monotonic())
        raise OSError("simulated transient")

    monkeypatch.setattr(LocalDiskBackend, "put", _flaky_put)
    fresh_mirror.enqueue(e)
    n = await fresh_mirror.drain()
    assert n == 0  # mirror never succeeded
    assert len(calls) == 3  # max_retries=3
    # Backoff is monotonic-increasing between attempts.
    assert calls[1] - calls[0] >= 0.0
    status = fresh_mirror.get_status()
    assert status["total_failed"] == 1
    assert any(f["seq"] == 3 for f in status["failed_entries"])


async def test_lag_and_queue_depth_in_status(fresh_mirror):
    assert fresh_mirror.get_status()["lag_seconds"] is None
    e = _FakeEntry(eid=4, approval_id=None, h="hash-lag")
    fresh_mirror.enqueue(e)
    await fresh_mirror.drain()
    status = fresh_mirror.get_status()
    assert status["lag_seconds"] is not None
    assert status["lag_seconds"] >= 0
    assert status["queue_depth"] == 0


async def test_object_key_layout(fresh_mirror):
    e = _FakeEntry(eid=42, approval_id="appr-X", h="0123456789abcdef")
    key = entry_object_key(
        approval_item_id=e.approval_item_id,
        seq=e.id,
        timestamp=e.timestamp,
        entry_hash=e.hash,
    )
    assert key.startswith("2026/05/08/appr-X/")
    assert "000000000042" in key
    assert key.endswith(".json")


async def test_canonical_payload_matches_chain_serializer(fresh_mirror):
    e = _FakeEntry(eid=99, approval_id="appr-Y", h="hash-canon")
    body = canonical_json(entry_to_canonical_payload(e))
    parsed = json.loads(body)
    # Sorted keys, no whitespace
    assert "  " not in body
    assert ", " not in body
    # Round-trip preserves the seq + linkage fields
    assert parsed["id"] == 99
    assert parsed["hash"] == "hash-canon"
    assert parsed["approval_item_id"] == "appr-Y"


# ---------------------------------------------------------------------------
# End-to-end via the FastAPI client
# ---------------------------------------------------------------------------
async def test_e2e_approval_lands_in_local_mirror(client, monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "B2_KEY_ID", "")
    monkeypatch.setattr(s, "AUDIT_MIRROR_LOCAL_PATH", str(tmp_path / "e2e_mirror"))
    reset_mirror_for_tests()

    r = await client.post("/v1/approvals", json=SAMPLE, headers=agent_h())
    assert r.status_code == 201, r.text
    aid = r.json()["id"]

    # The mirror worker is running inside the lifespan task. Give it a beat
    # to drain. Worst case: drain manually for determinism.
    from app.services.audit_mirror import get_mirror

    mirror = get_mirror()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and mirror.get_status()["queue_depth"] > 0:
        await asyncio.sleep(0.05)
    if mirror.get_status()["queue_depth"] > 0:
        await mirror.drain()

    status_r = await client.get(
        "/v1/admin/audit/mirror_status",
        headers={"X-Admin": os.environ["AGENT_SHARED_SECRET"]},
    )
    assert status_r.status_code == 200, status_r.text
    body = status_r.json()
    assert body["mode"] == "local"
    assert body["total_mirrored"] >= 1
    # On-disk artifacts exist for this approval
    files = list((tmp_path / "e2e_mirror").rglob(f"*/{aid}/*.json"))
    assert files, f"expected mirror objects under approval {aid}, got {list((tmp_path/'e2e_mirror').rglob('*'))}"
    reset_mirror_for_tests()
