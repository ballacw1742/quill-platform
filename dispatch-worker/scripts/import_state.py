"""One-time cutover: seed runtime_dispatch_state from the Mac daemons' JSON
state files so the Cloud Run worker doesn't re-dispatch historical uploads.

Usage (from repo root, with asyncpg installed):

    RUNTIME_STATE_DATABASE_URL='postgresql://...' \
    python dispatch-worker/scripts/import_state.py \
        contract=/Users/charlesmitchell/.openclaw/quill-daemons/state/contract-dispatcher.json \
        contract_review=/Users/charlesmitchell/.openclaw/quill-daemons/state/contract-review-dispatcher.json \
        classification=/Users/charlesmitchell/.openclaw/quill-daemons/state/classify-dispatcher.json \
        estimator=/Users/charlesmitchell/.openclaw/quill-daemons/state/estimate-dispatcher.json

Idempotent: uses INSERT ... ON CONFLICT DO NOTHING, so existing rows
(including newer worker-written ones) are never overwritten. Only
``dispatched`` entries are imported (as status='done'); historical error
entries are skipped — the worker will retry those items from scratch,
which is the desired behavior.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from runtime.state_store import _DDL, _parse_pg_dsn  # noqa: E402


async def main(pairs: list[tuple[str, Path]]) -> int:
    import asyncpg

    dsn = os.environ.get("RUNTIME_STATE_DATABASE_URL", "").strip()
    if not dsn:
        print("RUNTIME_STATE_DATABASE_URL is required", file=sys.stderr)
        return 2

    conn = await asyncpg.connect(**_parse_pg_dsn(dsn))
    try:
        await conn.execute(_DDL)
        total = 0
        for dispatcher, path in pairs:
            raw = json.loads(path.read_text(encoding="utf-8"))
            dispatched = raw.get("dispatched") or {}
            inserted = 0
            for item_id, entry in dispatched.items():
                try:
                    ts = datetime.fromisoformat(entry.get("dispatched_at") or "")
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=UTC)
                except ValueError:
                    ts = datetime.now(UTC)
                result = await conn.execute(
                    """
                    INSERT INTO runtime_dispatch_state
                        (dispatcher, item_id, status, approval_item_id,
                         dispatched_at, updated_at)
                    VALUES ($1, $2, 'done', $3, $4, now())
                    ON CONFLICT (dispatcher, item_id) DO NOTHING
                    """,
                    dispatcher,
                    str(item_id),
                    entry.get("approval_item_id"),
                    ts,
                )
                if result.endswith("1"):
                    inserted += 1
            print(
                f"[import_state] {dispatcher}: {inserted} inserted "
                f"({len(dispatched)} in file) from {path}"
            )
            total += inserted
        print(f"[import_state] done, {total} rows inserted")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    arg_pairs: list[tuple[str, Path]] = []
    for arg in sys.argv[1:]:
        name, _, p = arg.partition("=")
        if not p:
            print(f"bad arg (want name=path): {arg}", file=sys.stderr)
            sys.exit(2)
        arg_pairs.append((name, Path(p).expanduser()))
    if not arg_pairs:
        print(__doc__)
        sys.exit(2)
    sys.exit(asyncio.run(main(arg_pairs)))
