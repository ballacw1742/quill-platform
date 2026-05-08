#!/usr/bin/env python3
"""Replay a full week of synthetic activity in compressed wall-clock time.

Hits the dispatcher directly (bypassing APScheduler) for stress testing
the API + audit chain. Default: ~5 minutes of wall-clock = 7 simulated days.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

# Make `quill_mock_data` importable when run from the repo root.
HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "mock-data"))

from quill_mock_data.dispatcher import Dispatcher  # noqa: E402
from quill_mock_data.feeders import dfr as dfr_feeder  # noqa: E402
from quill_mock_data.feeders import hyperscaler as hyperscaler_feeder  # noqa: E402
from quill_mock_data.feeders import procurement as procurement_feeder  # noqa: E402
from quill_mock_data.feeders import rfi as rfi_feeder  # noqa: E402
from quill_mock_data.feeders import submittal as submittal_feeder  # noqa: E402


# Per simulated day:
#   ~10 RFIs, ~5 submittals, ~12 procurement updates, ~1 hyperscaler item,
#   4 DFRs (one per building).
DAILY_RATES = {
    "rfi": 10,
    "submittal": 5,
    "procurement": 12,
    "hyperscaler": 1,
    "dfr": None,  # uses dfr_feeder.tick which always emits 4
}


async def _run_one_day(dispatcher: Dispatcher, day: date) -> dict[str, int]:
    counts = {k: 0 for k in DAILY_RATES}
    rfis = rfi_feeder.tick(target_count=DAILY_RATES["rfi"], seed=int(day.toordinal()))
    subs = submittal_feeder.tick(target_count=DAILY_RATES["submittal"], seed=int(day.toordinal()) + 1)
    procs = procurement_feeder.tick(target_count=DAILY_RATES["procurement"], seed=int(day.toordinal()) + 2)
    hs = hyperscaler_feeder.tick(target_count=DAILY_RATES["hyperscaler"], seed=int(day.toordinal()) + 3)
    dfrs = dfr_feeder.tick(report_date=day, seed=int(day.toordinal()) + 4)

    for label, batch in (("rfi", rfis), ("submittal", subs), ("procurement", procs),
                        ("hyperscaler", hs), ("dfr", dfrs)):
        for ev in batch:
            await dispatcher.dispatch(ev)
            counts[label] += 1
    return counts


async def replay(days: int, wall_minutes: float, dry_run: bool) -> dict[str, object]:
    spacing_s = max(0.05, (wall_minutes * 60.0) / max(days, 1))
    grand: dict[str, int] = {}
    started = time.monotonic()
    base = date.today() - timedelta(days=days)
    async with Dispatcher(dry_run=dry_run) as dispatcher:
        for n in range(days):
            day = base + timedelta(days=n)
            day_counts = await _run_one_day(dispatcher, day)
            print(f"[day {n+1}/{days} {day.isoformat()}] {day_counts}", flush=True)
            for k, v in day_counts.items():
                grand[k] = grand.get(k, 0) + v
            await asyncio.sleep(spacing_s)
        final_stats = dict(dispatcher.stats)
    elapsed = time.monotonic() - started
    return {
        "elapsed_s": round(elapsed, 1),
        "days": days,
        "by_kind": grand,
        "dispatcher_stats": final_stats,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compressed-time week replay")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--minutes", type=float, default=5.0,
                        help="Wall-clock minutes to spread the simulation across.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    out = asyncio.run(replay(args.days, args.minutes, args.dry_run))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
