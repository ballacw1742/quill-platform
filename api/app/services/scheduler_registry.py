"""In-memory registry of scheduled jobs known to the platform.

The Telegram bot owns the actual APScheduler. It posts a heartbeat with its
job list to the API (PUT /v1/admin/scheduler/jobs/heartbeat — admin-gated).
The admin GET endpoint returns the most recent heartbeat plus a computed
"canonical schedule" so even if the bot is offline, operators can see what
*should* run.

This is intentionally tiny and process-local. Sprint 4+ will swap to Redis.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

log = logging.getLogger("quill.scheduler_registry")

ET = ZoneInfo("America/New_York")


@dataclass
class JobInfo:
    id: str
    name: str
    trigger: str
    next_run_at: str | None  # ISO 8601 in UTC
    source: str = "bot"  # 'bot' | 'canonical'
    last_run_at: str | None = None
    last_status: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _next_run_local(hour: int, minute: int = 0, *, tz: ZoneInfo = ET) -> str:
    """Compute the next wall-clock occurrence of HH:MM in `tz` and return UTC ISO."""
    now_local = datetime.now(tz)
    candidate = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now_local:
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC).isoformat()


def canonical_jobs() -> list[JobInfo]:
    """Static schedule the bot is *expected* to run."""
    return [
        JobInfo(
            id="daily-brief-fetch",
            name="Daily Brief — fetch inputs",
            trigger="cron(hour=6, minute=30, tz=America/New_York)",
            next_run_at=_next_run_local(6, 30),
            source="canonical",
        ),
        JobInfo(
            id="daily-brief-deliver",
            name="Daily Brief — Telegram + Drive delivery",
            trigger="cron(hour=7, minute=0, tz=America/New_York)",
            next_run_at=_next_run_local(7, 0),
            source="canonical",
        ),
        JobInfo(
            id="lane2-reminder-4h",
            name="Lane 2 reminder (>4h pending)",
            trigger="interval(minutes=15)",
            next_run_at=(datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
            source="canonical",
        ),
        JobInfo(
            id="lane2-escalate-8h",
            name="Lane 2 escalation (>8h pending)",
            trigger="interval(minutes=15)",
            next_run_at=(datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
            source="canonical",
        ),
        JobInfo(
            id="lane3-escalate-12h",
            name="Lane 3 escalation (>12h pending)",
            trigger="interval(minutes=30)",
            next_run_at=(datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
            source="canonical",
        ),
    ]


_state: dict[str, Any] = {
    "last_heartbeat_at": None,
    "bot_jobs": [],  # list[JobInfo]
}


def heartbeat(jobs: list[dict[str, Any]]) -> None:
    """Replace the bot's job list. Caller is admin-gated."""
    _state["last_heartbeat_at"] = datetime.now(UTC).isoformat()
    _state["bot_jobs"] = [
        JobInfo(
            id=str(j.get("id", "")),
            name=str(j.get("name", "")),
            trigger=str(j.get("trigger", "")),
            next_run_at=j.get("next_run_at"),
            source="bot",
            last_run_at=j.get("last_run_at"),
            last_status=j.get("last_status"),
            extra=j.get("extra", {}),
        )
        for j in jobs
    ]
    log.info("scheduler heartbeat received: %d jobs", len(_state["bot_jobs"]))


def snapshot() -> dict[str, Any]:
    bot_jobs: list[JobInfo] = _state["bot_jobs"]
    canonical = canonical_jobs()
    # Prefer bot's authoritative next_run_at when both list the same id.
    by_id = {j.id: j for j in canonical}
    for j in bot_jobs:
        by_id[j.id] = j
    merged = list(by_id.values())
    merged.sort(key=lambda j: j.next_run_at or "")
    return {
        "last_heartbeat_at": _state["last_heartbeat_at"],
        "bot_connected": _state["last_heartbeat_at"] is not None,
        "jobs": [j.__dict__ for j in merged],
    }
