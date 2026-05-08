#!/usr/bin/env python3
"""Nightly audit chain verification entry point.

Wired to OS cron at 02:00 ET (see AUDIT_VERIFY_SCHEDULE_CRON in .env).

Walks both Postgres and the offsite mirror, persists a verification row, and
on any non-OK result:
  - touches the freeze flag (audit writes pause)
  - emits a Sentry message
  - exits non-zero so cron-mailers / SystemD OnFailure pick it up

Usage:
  python -m scripts.audit_verify_run               # full chain, persist
  python -m scripts.audit_verify_run --approval ID  # per-approval scope
  python -m scripts.audit_verify_run --no-persist   # dry run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any


def _ensure_path() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    api_root = os.path.normpath(os.path.join(here, ".."))
    if api_root not in sys.path:
        sys.path.insert(0, api_root)


_ensure_path()


async def _run(args: argparse.Namespace) -> int:
    from app.db import SessionLocal  # noqa: PLC0415
    from app.models import AuditLogEntry  # noqa: PLC0415
    from app.services import audit_verify as verify_svc  # noqa: PLC0415
    from app.services.audit_mirror import (  # noqa: PLC0415
        canonical_json,
        entry_object_key,
        entry_to_canonical_payload,
        get_mirror,
    )
    from sqlalchemy import select  # noqa: PLC0415

    if args.drain:
        # Bulk-mirror any Postgres entries that aren't on disk yet. This makes
        # the script safe to run after a seed/replay where the in-process
        # worker never had a chance to drain.
        mirror = get_mirror()
        async with SessionLocal() as session:
            entries = (await session.execute(
                select(AuditLogEntry).order_by(AuditLogEntry.id.asc())
            )).scalars().all()
        existing = set(await mirror.backend.list_keys())
        synced = 0
        for e in entries:
            key = entry_object_key(
                approval_item_id=e.approval_item_id,
                seq=e.id,
                timestamp=e.timestamp,
                entry_hash=e.hash,
            )
            if key in existing:
                continue
            body = canonical_json(entry_to_canonical_payload(e)).encode("utf-8")
            await mirror.backend.put(key, body)
            synced += 1
        if synced:
            print(f"[info] sync-drained {synced} entries to mirror before verify")

    async with SessionLocal() as session:
        if args.approval:
            result = await verify_svc.verify_per_approval(
                session,
                args.approval,
                triggered_by=args.triggered_by,
                persist=not args.no_persist,
            )
        else:
            result = await verify_svc.verify_full_chain(
                session,
                triggered_by=args.triggered_by,
                persist=not args.no_persist,
            )

    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


def _jsonable(o: Any) -> Any:
    if hasattr(o, "isoformat"):
        return o.isoformat()
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_jsonable(v) for v in o]
    return o


def main() -> int:
    p = argparse.ArgumentParser(description="Nightly audit chain verification.")
    p.add_argument("--approval", default=None, help="Verify a single approval's sub-chain.")
    p.add_argument("--no-persist", action="store_true", help="Do not write a verification row.")
    p.add_argument("--triggered-by", default="cron")
    p.add_argument(
        "--drain",
        action="store_true",
        help="First mirror any unmirrored Postgres entries (useful after seed/restore).",
    )
    args = p.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
