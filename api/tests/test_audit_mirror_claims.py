"""Sprint-4 fix #8: audit-mirror replica claim mechanism.

Multi-replica deploys would each enqueue + write the same audit-log entry
to B2. With the claim table only the replica that wins the
INSERT ... ON CONFLICT DO NOTHING RETURNING hash race actually pays for
the B2 PUT.

These tests exercise:
  - Single-replica still works (claim_in_postgres=False, the default).
  - Two AuditMirror instances pointing at the same in-process claim set
    (simulating shared Postgres) pick exactly one winner per entry.
  - Lost-claim path increments the skip counter and does NOT call B2.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from app.services.audit_mirror import (
    AuditMirror,
    LocalDiskBackend,
    _PendingMirror,
)


class _SpyBackend(LocalDiskBackend):
    """LocalDiskBackend that counts puts so we can assert at-most-once."""

    def __init__(self, root) -> None:  # noqa: D401
        super().__init__(root)
        self.put_calls = 0

    async def put(self, key: str, body: bytes) -> dict[str, Any]:
        self.put_calls += 1
        return await super().put(key, body)


def _pending(seq: int = 1, h: str = "h" * 64) -> _PendingMirror:
    return _PendingMirror(
        seq=seq,
        approval_item_id="ap-1",
        timestamp=datetime.now(UTC),
        entry_hash=h,
        canonical_body=b'{"x":1}',
    )


# ---------------------------------------------------------------------------
# Single-replica path (claim_in_postgres=False)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_single_replica_writes_each_entry_once(tmp_path):
    backend = _SpyBackend(tmp_path)
    mirror = AuditMirror(backend, max_retries=1, claim_in_postgres=False)
    p1 = _pending(seq=1, h="a" * 64)
    p2 = _pending(seq=2, h="b" * 64)
    assert await mirror._mirror_one(p1) is True
    assert await mirror._mirror_one(p2) is True
    assert backend.put_calls == 2

    # Re-mirroring the same hash is a no-op (local claim already taken)
    assert await mirror._mirror_one(p1) is True
    assert backend.put_calls == 2  # unchanged


@pytest.mark.asyncio
async def test_status_reports_claim_metrics(tmp_path):
    backend = _SpyBackend(tmp_path)
    mirror = AuditMirror(backend, max_retries=1, claim_in_postgres=False)
    await mirror._mirror_one(_pending(seq=1, h="z" * 64))
    await mirror._mirror_one(_pending(seq=1, h="z" * 64))  # dup
    s = mirror.get_status()
    assert s["claim_total"] == 2
    assert s["claim_skipped"] == 1
    assert s["claim_in_postgres"] is False


# ---------------------------------------------------------------------------
# Multi-replica simulation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_two_replicas_share_claim_set_one_winner(tmp_path):
    """Simulate two replicas by giving them a *shared* in-process claim set.

    In production the claim is in Postgres so the unique-PK does the same job;
    we sub the Postgres path with a shared set so the test stays hermetic.
    """
    backend_a = _SpyBackend(tmp_path / "a")
    backend_b = _SpyBackend(tmp_path / "b")
    a = AuditMirror(backend_a, max_retries=1, claim_in_postgres=False)
    b = AuditMirror(backend_b, max_retries=1, claim_in_postgres=False)
    # Bind both mirrors to the same set under the same lock to simulate
    # the strict serializability that Postgres provides for the unique PK.
    import threading

    shared_lock = threading.Lock()
    shared: set[str] = set()
    a._local_claims = shared
    b._local_claims = shared
    a._local_claims_lock = shared_lock
    b._local_claims_lock = shared_lock

    pending_hash = "c" * 64
    # Race: both replicas try to claim concurrently. Exactly one should win.
    results = await asyncio.gather(
        a._mirror_one(_pending(seq=1, h=pending_hash)),
        b._mirror_one(_pending(seq=1, h=pending_hash)),
    )
    assert all(results)  # neither raised; both succeeded as a method call
    # But only one actually wrote bytes:
    assert backend_a.put_calls + backend_b.put_calls == 1


@pytest.mark.asyncio
async def test_lost_claim_does_not_invoke_backend(tmp_path):
    backend = _SpyBackend(tmp_path)
    mirror = AuditMirror(backend, max_retries=1, claim_in_postgres=False)
    h = "d" * 64
    # Pre-populate the claim set so the next attempt loses immediately.
    mirror._local_claims.add(h)
    p = _pending(seq=99, h=h)
    ok = await mirror._mirror_one(p)
    assert ok is True
    assert backend.put_calls == 0
    s = mirror.get_status()
    assert s["claim_skipped"] == 1
