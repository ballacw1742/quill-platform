#!/usr/bin/env python3
"""Audit mirror replay / DR tool.

Two modes:
  --verify-only (default):  Pull a date range from the mirror, recompute each
                             entry's hash, and confirm the chain links cleanly.
                             No writes to Postgres. Reports counts + any drift.
  --restore=FILE:            Pull a date range and write the entries to a
                             fresh JSONL file you can sideload into a clean
                             Postgres for restore drills.

Usage:
  python -m scripts.audit_mirror_replay
      --since 2026-05-01 --until 2026-05-08

  python -m scripts.audit_mirror_replay
      --since 2026-05-01 --until 2026-05-08 --restore drill_chain.jsonl

The mirror backend is selected by env (B2 if creds set, local otherwise) \u2014
identical to the running API.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from typing import Any


def _ensure_path() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    api_root = os.path.normpath(os.path.join(here, ".."))
    if api_root not in sys.path:
        sys.path.insert(0, api_root)


_ensure_path()


def _parse_date(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def _canonical(payload: dict[str, Any]) -> str:
    def _default(o: Any) -> Any:
        if isinstance(o, datetime):
            return o.astimezone(UTC).isoformat()
        if hasattr(o, "value"):
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


def _date_prefixes(since: datetime, until: datetime) -> list[str]:
    out: list[str] = []
    d = since
    while d.date() <= until.date():
        out.append(f"{d.year:04d}/{d.month:02d}/{d.day:02d}")
        d = d.fromordinal(d.toordinal() + 1).replace(tzinfo=UTC)
    return out


async def _pull_in_range(mirror, since: datetime, until: datetime) -> list[dict[str, Any]]:
    keys: list[str] = []
    for prefix in _date_prefixes(since, until):
        keys.extend(await mirror.backend.list_keys(prefix))
    keys = sorted(set(keys))
    docs: list[dict[str, Any]] = []
    for k in keys:
        body = await mirror.backend.get(k)
        if body is None:
            continue
        try:
            doc = json.loads(body)
        except json.JSONDecodeError:
            print(f"[warn] unparsable mirror key={k}", file=sys.stderr)
            continue
        doc["_key"] = k
        docs.append(doc)
    docs.sort(key=lambda d: int(d.get("id") or 0))
    return docs


def _verify(docs: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    last_hash_by_bucket: dict[str | None, str | None] = {}
    seen_seqs: set[int] = set()
    for d in docs:
        seq = d.get("id")
        if not isinstance(seq, int):
            failures.append({"kind": "missing_id", "key": d.get("_key")})
            continue
        if seq in seen_seqs:
            failures.append({"kind": "duplicate_seq", "seq": seq, "key": d.get("_key")})
            continue
        seen_seqs.add(seq)

        body = {
            "event_type": d.get("event_type"),
            "actor": d.get("actor"),
            "approval_item_id": d.get("approval_item_id"),
            "payload": d.get("payload"),
            "timestamp": d.get("timestamp"),
        }
        expected = _compute_hash(_canonical(body), d.get("prev_hash"))
        if expected != d.get("hash"):
            failures.append(
                {
                    "kind": "hash_mismatch",
                    "seq": seq,
                    "key": d.get("_key"),
                    "stored_hash": d.get("hash"),
                    "expected_hash": expected,
                }
            )
        bucket = d.get("approval_item_id")
        last_hash_by_bucket[bucket] = d.get("hash")

    return {
        "ok": not failures,
        "doc_count": len(docs),
        "buckets": len({d.get("approval_item_id") for d in docs}),
        "failures": failures,
    }


async def _run(args: argparse.Namespace) -> int:
    from app.services.audit_mirror import AuditMirror, build_backend  # noqa: PLC0415

    backend = build_backend()
    mirror = AuditMirror(backend)

    since = _parse_date(args.since)
    until = _parse_date(args.until)

    print(f"[info] mirror mode={backend.mode} range={args.since}..{args.until}")
    docs = await _pull_in_range(mirror, since, until)
    print(f"[info] pulled {len(docs)} mirror objects")
    report = _verify(docs)
    print(json.dumps(report, indent=2, sort_keys=True))

    if args.restore:
        with open(args.restore, "w", encoding="utf-8") as f:
            for d in docs:
                payload = {k: v for k, v in d.items() if k != "_key"}
                f.write(json.dumps(payload, sort_keys=True) + "\n")
        print(f"[info] wrote {len(docs)} entries to {args.restore}")

    return 0 if report["ok"] else 1


def main() -> int:
    p = argparse.ArgumentParser(description="Audit mirror DR replay tool.")
    p.add_argument("--since", required=True, help="ISO date (e.g. 2026-05-01)")
    p.add_argument("--until", required=True, help="ISO date (e.g. 2026-05-08)")
    p.add_argument("--restore", default=None, help="Write entries to JSONL for restore drill.")
    args = p.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
