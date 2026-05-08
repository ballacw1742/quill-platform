"""Two-tier audit chain verification.

Walks both the Postgres chain and the offsite mirror (B2 or local) and:
  1. Recomputes each entry's hash and confirms it matches the stored hash
  2. Confirms each Postgres entry is mirrored, and vice versa
  3. Persists the result into `audit_chain_verifications` so the admin UI
     and ops cron can show a history

Result enum:
  ok               — both stores consistent end-to-end
  postgres_drift   — at least one Postgres row's hash doesn't match recompute
  b2_drift         — mirror object exists but its hash doesn't match Postgres
  mismatch         — postgres↔mirror set difference (entries in one not other)
  missing          — at least one Postgres entry has no mirror object
  error            — verification could not complete (e.g. backend down)

On any non-OK result the service:
  - writes the verification row with details
  - touches the freeze flag (so subsequent record_event raises AuditFrozenError)
  - emits a Sentry message (best-effort, soft-imported)
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import AuditChainVerification, AuditLogEntry
from app.services.audit import _canonical, _compute_hash
from app.services.audit_mirror import (
    AuditMirror,
    canonical_json,
    entry_to_canonical_payload,
    get_mirror,
)

log = logging.getLogger("quill.audit_verify")


# ---------------------------------------------------------------------------
# Postgres-only verification (tamper-proof check on the primary store)
# ---------------------------------------------------------------------------
def _entry_recompute_hash(entry: AuditLogEntry) -> str:
    ts = entry.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    else:
        ts = ts.astimezone(UTC)
    body = {
        "event_type": entry.event_type,
        "actor": entry.actor,
        "approval_item_id": entry.approval_item_id,
        "payload": entry.payload,
        "timestamp": ts.isoformat(),
    }
    return _compute_hash(_canonical(body), entry.prev_hash)


async def _load_postgres_entries(
    session: AsyncSession,
    *,
    approval_item_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[AuditLogEntry]:
    stmt = select(AuditLogEntry).order_by(AuditLogEntry.id.asc())
    if approval_item_id is not None:
        stmt = stmt.where(AuditLogEntry.approval_item_id == approval_item_id)
    if since is not None:
        stmt = stmt.where(AuditLogEntry.timestamp >= since)
    if until is not None:
        stmt = stmt.where(AuditLogEntry.timestamp <= until)
    res = await session.execute(stmt)
    return list(res.scalars().all())


# ---------------------------------------------------------------------------
# Mirror loading
# ---------------------------------------------------------------------------
async def _load_mirror_entries(
    mirror: AuditMirror,
    *,
    approval_item_id: str | None = None,
) -> dict[int, dict[str, Any]]:
    """Return {seq -> mirror_doc} from the backend.

    Mirror keys encode the seq as a 12-digit zero-padded prefix in the filename,
    after the date/bucket path. We slurp every JSON object and reconstruct a
    seq-keyed dict. If `approval_item_id` is set, restrict to docs whose payload
    references that approval (so per-approval scope is symmetric to Postgres).
    """
    keys = await mirror.backend.list_keys()
    out: dict[int, dict[str, Any]] = {}
    for key in keys:
        body = await mirror.backend.get(key)
        if body is None:
            continue
        try:
            doc = json.loads(body)
        except json.JSONDecodeError:
            log.warning("audit_verify: skipping unparsable mirror object key=%s", key)
            continue
        if approval_item_id is not None and doc.get("approval_item_id") != approval_item_id:
            continue
        seq = doc.get("id")
        if isinstance(seq, int):
            out[seq] = {**doc, "_key": key}
    return out


# ---------------------------------------------------------------------------
# Result construction
# ---------------------------------------------------------------------------
def _check_subchain(entries: list[AuditLogEntry]) -> list[dict[str, Any]]:
    """Per-entry hash + linkage check. Returns failure dicts (empty if ok)."""
    failures: list[dict[str, Any]] = []
    last_hash: str | None = None
    for idx, e in enumerate(entries):
        expected = _entry_recompute_hash(e)
        if expected != e.hash:
            failures.append(
                {
                    "kind": "hash_mismatch",
                    "entry_id": e.id,
                    "approval_item_id": e.approval_item_id,
                    "stored_hash": e.hash,
                    "expected_hash": expected,
                }
            )
        if idx == 0:
            if e.prev_hash is not None:
                failures.append(
                    {
                        "kind": "chain_break_genesis",
                        "entry_id": e.id,
                        "approval_item_id": e.approval_item_id,
                        "prev_hash": e.prev_hash,
                    }
                )
        else:
            if e.prev_hash != last_hash:
                failures.append(
                    {
                        "kind": "chain_break",
                        "entry_id": e.id,
                        "approval_item_id": e.approval_item_id,
                        "prev_hash_stored": e.prev_hash,
                        "prev_hash_actual": last_hash,
                    }
                )
        last_hash = e.hash
    return failures


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def verify_chain_integrity(
    session: AsyncSession,
    *,
    scope: str = "global",
    scope_ref: str | None = None,
    approval_item_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    triggered_by: str = "manual",
    mirror: AuditMirror | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Walk both stores. Returns a result dict and (by default) persists a row."""
    started = datetime.now(UTC)
    t0 = time.monotonic()
    mirror = mirror or get_mirror()

    pg_entries = await _load_postgres_entries(
        session,
        approval_item_id=approval_item_id,
        since=since,
        until=until,
    )

    # Bucket Postgres entries by approval_item_id for sub-chain verification.
    buckets: dict[str | None, list[AuditLogEntry]] = {}
    for e in pg_entries:
        buckets.setdefault(e.approval_item_id, []).append(e)

    pg_failures: list[dict[str, Any]] = []
    for k, items in buckets.items():
        pg_failures.extend(_check_subchain(items))

    mirror_docs = await _load_mirror_entries(
        mirror, approval_item_id=approval_item_id
    )

    pg_seqs = {int(e.id) for e in pg_entries}
    mirror_seqs = set(mirror_docs.keys())

    # Cross-checks
    missing_in_mirror: list[int] = []
    missing_in_postgres: list[int] = []
    b2_failures: list[dict[str, Any]] = []

    for e in pg_entries:
        seq = int(e.id)
        doc = mirror_docs.get(seq)
        if doc is None:
            missing_in_mirror.append(seq)
            continue
        if doc.get("hash") != e.hash:
            b2_failures.append(
                {
                    "kind": "b2_hash_mismatch",
                    "entry_id": seq,
                    "approval_item_id": e.approval_item_id,
                    "postgres_hash": e.hash,
                    "mirror_hash": doc.get("hash"),
                    "key": doc.get("_key"),
                }
            )
        else:
            # Recompute from canonical body too — defends against b2 storing
            # a tampered doc whose .hash field happens to match (unlikely, but
            # a self-consistent forgery would still fail recompute).
            recomputed_doc = entry_to_canonical_payload(e)
            recomputed_canonical = canonical_json(recomputed_doc).encode("utf-8")
            actual_doc_canonical = canonical_json(
                {k2: v2 for k2, v2 in doc.items() if k2 != "_key"}
            ).encode("utf-8")
            if actual_doc_canonical != recomputed_canonical:
                b2_failures.append(
                    {
                        "kind": "b2_body_drift",
                        "entry_id": seq,
                        "approval_item_id": e.approval_item_id,
                        "key": doc.get("_key"),
                    }
                )

    for seq in mirror_seqs - pg_seqs:
        missing_in_postgres.append(seq)

    # Decide top-level result. Order matters — first non-empty wins for the label,
    # but we keep all failure detail in `details`.
    result: str = "ok"
    if pg_failures:
        result = "postgres_drift"
    elif b2_failures:
        result = "b2_drift"
    elif missing_in_mirror or missing_in_postgres:
        result = "missing" if missing_in_mirror and not missing_in_postgres else "mismatch"

    last_pg_hash = pg_entries[-1].hash if pg_entries else None
    last_mirror_hash: str | None = None
    if mirror_docs:
        max_seq = max(mirror_docs.keys())
        last_mirror_hash = mirror_docs[max_seq].get("hash")

    duration_ms = int((time.monotonic() - t0) * 1000)
    finished = datetime.now(UTC)

    details = {
        "postgres_failures": pg_failures,
        "b2_failures": b2_failures,
        "missing_in_mirror": sorted(missing_in_mirror),
        "missing_in_postgres": sorted(missing_in_postgres),
        "approval_item_id": approval_item_id,
        "since": since.isoformat() if since else None,
        "until": until.isoformat() if until else None,
        "mirror_mode": mirror.backend.mode,
    }

    if persist:
        row = AuditChainVerification(
            started_at=started,
            finished_at=finished,
            duration_ms=duration_ms,
            scope=scope,
            scope_ref=scope_ref or approval_item_id,
            result=result,
            chain_length_postgres=len(pg_entries),
            chain_length_mirror=len(mirror_docs),
            last_hash_postgres=last_pg_hash,
            last_hash_mirror=last_mirror_hash,
            details=details,
            triggered_by=triggered_by,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        result_id = row.id
    else:
        result_id = None

    payload = {
        "id": result_id,
        "ok": result == "ok",
        "result": result,
        "scope": scope,
        "scope_ref": scope_ref or approval_item_id,
        "chain_length_postgres": len(pg_entries),
        "chain_length_mirror": len(mirror_docs),
        "last_hash_postgres": last_pg_hash,
        "last_hash_mirror": last_mirror_hash,
        "duration_ms": duration_ms,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "details": details,
    }

    if result != "ok":
        _on_failure(payload)

    return payload


async def verify_full_chain(
    session: AsyncSession,
    *,
    triggered_by: str = "cron",
    persist: bool = True,
) -> dict[str, Any]:
    return await verify_chain_integrity(
        session,
        scope="global",
        triggered_by=triggered_by,
        persist=persist,
    )


async def verify_per_approval(
    session: AsyncSession,
    approval_id: str,
    *,
    triggered_by: str = "manual",
    persist: bool = True,
) -> dict[str, Any]:
    return await verify_chain_integrity(
        session,
        scope="per_approval",
        scope_ref=approval_id,
        approval_item_id=approval_id,
        triggered_by=triggered_by,
        persist=persist,
    )


async def list_recent_verifications(
    session: AsyncSession, *, limit: int = 25
) -> list[AuditChainVerification]:
    res = await session.execute(
        select(AuditChainVerification)
        .order_by(AuditChainVerification.started_at.desc())
        .limit(limit)
    )
    return list(res.scalars().all())


# ---------------------------------------------------------------------------
# Failure side-effects
# ---------------------------------------------------------------------------
def _on_failure(payload: dict[str, Any]) -> None:
    """Touch freeze flag + page Charles via Sentry / notifier (soft-import)."""
    s = get_settings()
    try:
        flag = s.AUDIT_FREEZE_FLAG_PATH
        if flag:
            os.makedirs(os.path.dirname(flag) or ".", exist_ok=True)
            with open(flag, "w", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "frozen_at": datetime.now(UTC).isoformat(),
                            "result": payload["result"],
                            "verification_id": payload.get("id"),
                        },
                        sort_keys=True,
                    )
                )
    except OSError as exc:
        log.error("audit_verify: failed to write freeze flag: %s", exc)

    # Sentry (best-effort)
    try:
        from app.services import sentry as _sentry  # type: ignore

        if hasattr(_sentry, "capture_message"):
            _sentry.capture_message(
                f"audit chain verification failed: {payload['result']}",
                level="error",
                verification_id=payload.get("id") or "",
                scope=payload.get("scope") or "",
                postgres_failures=str(len(payload["details"]["postgres_failures"])),
                b2_failures=str(len(payload["details"]["b2_failures"])),
                missing_in_mirror=str(len(payload["details"]["missing_in_mirror"])),
            )
            return
    except Exception:  # noqa: BLE001
        pass
    try:
        import sentry_sdk

        sentry_sdk.capture_message(
            f"audit chain verification failed: {payload['result']}", level="error"
        )
    except Exception:  # noqa: BLE001
        log.error("audit_verify: failure but no sentry channel available")


def clear_freeze_flag() -> bool:
    """Remove the freeze touch-file. Returns True if a file was removed."""
    s = get_settings()
    if s.AUDIT_FREEZE_FLAG_PATH and os.path.exists(s.AUDIT_FREEZE_FLAG_PATH):
        os.remove(s.AUDIT_FREEZE_FLAG_PATH)
        return True
    return False


__all__ = [
    "verify_chain_integrity",
    "verify_full_chain",
    "verify_per_approval",
    "list_recent_verifications",
    "clear_freeze_flag",
]
