"""Append-only sha256-chained audit log.

Every state change MUST funnel through `record_event`. Tampering is detected
by `verify_chain`.

Sprint 2.3 adds an offsite mirror: `record_event_with_mirror` is the new
preferred entry point and chains the existing `record_event` with an
async push to `app.services.audit_mirror`. The legacy `record_event` is
kept for backwards compat (and is the path approvals.py + sla.py already
use — they both flow through the dispatcher below).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import AuditLogEntry

log = logging.getLogger("quill.audit")


def _canonical(payload: dict[str, Any]) -> str:
    """Deterministic JSON for hashing. Sort keys, no whitespace, default str for datetime."""

    def _default(o: Any) -> Any:
        if isinstance(o, datetime):
            return o.astimezone(UTC).isoformat()
        if hasattr(o, "value"):  # enum
            return o.value
        return str(o)

    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_default)


def _compute_hash(canonical_payload: str, prev_hash: str | None) -> str:
    h = hashlib.sha256()
    if prev_hash:
        h.update(prev_hash.encode("utf-8"))
    h.update(b"|")
    h.update(canonical_payload.encode("utf-8"))
    return h.hexdigest()


async def _latest_hash(
    session: AsyncSession, approval_item_id: str | None
) -> tuple[str | None, int | None]:
    """Return (latest_hash, latest_id) for the chain scoped to this approval (or global)."""
    stmt = select(AuditLogEntry).order_by(AuditLogEntry.id.desc())
    if approval_item_id is not None:
        stmt = stmt.where(AuditLogEntry.approval_item_id == approval_item_id)
    else:
        stmt = stmt.where(AuditLogEntry.approval_item_id.is_(None))
    res = await session.execute(stmt.limit(1))
    last = res.scalars().first()
    if last is None:
        return None, None
    return last.hash, last.id


def is_audit_frozen() -> bool:
    """Truthy when the freeze touch-file is present. The nightly verify writes
    this on a non-OK result; presence blocks new audit writes until ops clears it.
    """
    s = get_settings()
    return bool(s.AUDIT_FREEZE_FLAG_PATH) and os.path.exists(s.AUDIT_FREEZE_FLAG_PATH)


class AuditFrozenError(RuntimeError):
    """Raised when the audit chain is in freeze mode and a write is attempted."""


async def record_event(
    session: AsyncSession,
    *,
    event_type: str,
    actor: str,
    approval_item_id: str | None,
    payload: dict[str, Any],
    mirror: bool = True,
) -> AuditLogEntry:
    """Append a chained event. Returns the new AuditLogEntry (not yet committed).

    If `mirror=True` (default), the entry is also pushed to the offsite mirror
    queue immediately after the SQLAlchemy flush. The actual upload happens
    asynchronously — the caller is *not* blocked on B2 latency.
    """
    if is_audit_frozen():
        raise AuditFrozenError(
            "audit chain is frozen — a verification failure has paused writes"
        )
    prev_hash, _ = await _latest_hash(session, approval_item_id)
    ts = datetime.now(UTC)
    body = {
        "event_type": event_type,
        "actor": actor,
        "approval_item_id": approval_item_id,
        "payload": payload,
        "timestamp": ts.isoformat(),
    }
    canonical = _canonical(body)
    new_hash = _compute_hash(canonical, prev_hash)

    entry = AuditLogEntry(
        event_type=event_type,
        actor=actor,
        approval_item_id=approval_item_id,
        payload=payload,
        timestamp=ts,
        hash=new_hash,
        prev_hash=prev_hash,
    )
    session.add(entry)
    await session.flush()
    if mirror:
        try:
            from app.services.audit_mirror import get_mirror

            get_mirror().enqueue(entry)
        except Exception as exc:  # noqa: BLE001
            # Mirror enqueue must NEVER block the primary audit write.
            log.warning("audit_mirror enqueue failed for entry=%s err=%s", entry.id, exc)
    return entry


async def record_event_with_mirror(
    session: AsyncSession,
    *,
    event_type: str,
    actor: str,
    approval_item_id: str | None,
    payload: dict[str, Any],
) -> AuditLogEntry:
    """Explicitly mirrored variant. Identical to `record_event(mirror=True)`,
    kept as a named entry point so callers can opt-in unambiguously.
    """
    return await record_event(
        session,
        event_type=event_type,
        actor=actor,
        approval_item_id=approval_item_id,
        payload=payload,
        mirror=True,
    )


def _verify_subchain(entries: list[AuditLogEntry]) -> tuple[list[str], str | None]:
    """Verify a single ordered chain. Returns (failures, last_hash)."""
    failures: list[str] = []
    last_hash: str | None = None
    for idx, e in enumerate(entries):
        ts = e.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        else:
            ts = ts.astimezone(UTC)
        body = {
            "event_type": e.event_type,
            "actor": e.actor,
            "approval_item_id": e.approval_item_id,
            "payload": e.payload,
            "timestamp": ts.isoformat(),
        }
        canonical = _canonical(body)
        expected = _compute_hash(canonical, e.prev_hash)
        if expected != e.hash:
            failures.append(f"hash_mismatch:entry_id={e.id}")
        # Linkage check: each entry must reference the prior entry's hash.
        if idx == 0:
            if e.prev_hash is not None:
                failures.append(f"chain_break:entry_id={e.id}:expected_genesis")
        else:
            if e.prev_hash != last_hash:
                failures.append(f"chain_break:entry_id={e.id}")
        last_hash = e.hash
    return failures, last_hash


async def verify_chain(
    session: AsyncSession, approval_item_id: str | None = None
) -> dict[str, Any]:
    """Walk and verify the chain. If approval_item_id is None, walks every per-item
    sub-chain plus the (possibly empty) global-only sub-chain (entries with no item).
    """
    stmt = select(AuditLogEntry).order_by(AuditLogEntry.id.asc())
    if approval_item_id is not None:
        stmt = stmt.where(AuditLogEntry.approval_item_id == approval_item_id)
        res = await session.execute(stmt)
        entries = list(res.scalars().all())
        failures, last_hash = _verify_subchain(entries)
        return {
            "ok": not failures,
            "chain_length": len(entries),
            "last_hash": last_hash,
            "failures": failures,
        }

    # Global: bucket by approval_item_id (None bucket allowed too) and verify each.
    res = await session.execute(stmt)
    all_entries = list(res.scalars().all())
    buckets: dict[str | None, list[AuditLogEntry]] = {}
    for e in all_entries:
        buckets.setdefault(e.approval_item_id, []).append(e)

    failures: list[str] = []
    last_global_hash: str | None = None
    for key, items in buckets.items():
        sub_failures, last = _verify_subchain(items)
        if sub_failures:
            failures.extend([f"bucket={key}:{f}" for f in sub_failures])
        last_global_hash = last

    return {
        "ok": not failures,
        "chain_length": len(all_entries),
        "last_hash": last_global_hash,
        "failures": failures,
    }


async def latest_global_hash(session: AsyncSession) -> str | None:
    """Returns the most recent audit hash across all entries (for health endpoint)."""
    res = await session.execute(
        select(AuditLogEntry.hash).order_by(AuditLogEntry.id.desc()).limit(1)
    )
    return res.scalar_one_or_none()
