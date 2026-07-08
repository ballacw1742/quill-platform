"""Per-tenant fixed-window rate limits (contract: LIMITS.md §3).

One upsert-increment per limited request against agentcloud_rate_limits,
keyed by (tenant_id, bucket, window_start) where window_start is the current
UTC minute boundary. The counter lives in the shared Postgres both
orchestrator instances already use (same discipline as the SKIP LOCKED
scheduler claim) — no Redis/memorystore, multi-instance-safe by construction.

Tradeoff (documented in LIMITS.md §3): a fixed window is not a true sliding
window; a client can burst up to 2× the limit across a window boundary. That
is acceptable for an abuse-control limit and is the simplest mechanism that
is multi-instance-safe with existing infra.

Rows two windows old for the same (tenant, bucket) are opportunistically
deleted on the increment path, so the table stays O(tenants × buckets).

`rate_limit.exceeded` is evented at most once per (tenant, bucket, window):
the FIRST rejected request of the window is the one whose returned count is
exactly limit+1, so an abusive client cannot flood the events table.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from app import events as events_mod
from app.config import get_settings
from app.models import RateLimit

log = logging.getLogger("agentcloud.ratelimit")

WINDOW_SECONDS = 60

# bucket -> config attribute holding the per-minute limit (0 disables).
_BUCKET_CONFIG = {
    "chat": "RATE_LIMIT_PER_MIN",
    "jobs": "RATE_LIMIT_JOBS_PER_MIN",
}

# Injectable clock for tests (fake clock); defaults to real UTC now.
_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


def set_clock(fn: Callable[[], datetime] | None) -> None:
    """Test hook: pin/reset the clock used for window math."""
    global _clock
    _clock = fn or (lambda: datetime.now(timezone.utc))


def _now() -> datetime:
    return _clock()


def window_start(now: datetime) -> datetime:
    """Truncate to the current UTC minute boundary."""
    return now.replace(second=0, microsecond=0)


def _limit_for(bucket: str) -> int:
    attr = _BUCKET_CONFIG.get(bucket)
    if attr is None:
        raise ValueError(f"unknown rate-limit bucket {bucket!r} (chat|jobs)")
    return int(getattr(get_settings(), attr))


@dataclass
class RateLimitDecision:
    allowed: bool
    limit: int
    count: int
    retry_after_seconds: int
    # True only on the FIRST rejected request of a (tenant, bucket, window)
    first_rejection: bool = False


class RateLimitExceeded(Exception):
    """Raised by enforce() when a request is over the per-tenant limit."""

    def __init__(self, decision: RateLimitDecision, bucket: str) -> None:
        self.decision = decision
        self.bucket = bucket
        super().__init__(
            f"rate limit exceeded: {decision.limit}/min per tenant for "
            f"{bucket} — retry after {decision.retry_after_seconds}s"
        )

    @property
    def detail(self) -> str:
        return str(self)


def _upsert_increment(model_cls, values: dict, dialect: str):
    if dialect == "postgresql":
        stmt = postgresql.insert(model_cls).values(**values)
        return stmt.on_conflict_do_update(
            index_elements=["tenant_id", "bucket", "window_start"],
            set_={"count": model_cls.count + 1},
        )
    stmt = sqlite.insert(model_cls).values(**values)
    return stmt.on_conflict_do_update(
        index_elements=["tenant_id", "bucket", "window_start"],
        set_={"count": model_cls.count + 1},
    )


async def check(session: AsyncSession, tenant_id: str, bucket: str) -> RateLimitDecision:
    """Count this request against (tenant, bucket, current-minute).

    Runs inside an existing tenant transaction (RLS second belt). Returns a
    decision; does NOT raise. The limit is inclusive: the (limit+1)-th
    request in a window is the first rejection.
    """
    limit = _limit_for(bucket)
    now = _now()
    win = window_start(now)
    if limit <= 0:  # bucket disabled
        return RateLimitDecision(allowed=True, limit=0, count=0, retry_after_seconds=0)

    # opportunistic GC: drop windows two minutes old for this (tenant, bucket)
    await session.execute(
        sa.delete(RateLimit).where(
            RateLimit.tenant_id == tenant_id,
            RateLimit.bucket == bucket,
            RateLimit.window_start < win - timedelta(seconds=2 * WINDOW_SECONDS),
        )
    )

    dialect = session.bind.dialect.name if session.bind is not None else "sqlite"
    await session.execute(
        _upsert_increment(
            RateLimit,
            {
                "tenant_id": tenant_id,
                "bucket": bucket,
                "window_start": win,
                "count": 1,
            },
            dialect,
        )
    )
    count = (
        await session.execute(
            sa.select(RateLimit.count).where(
                RateLimit.tenant_id == tenant_id,
                RateLimit.bucket == bucket,
                RateLimit.window_start == win,
            )
        )
    ).scalar_one()

    # seconds until the window ends (>= 1)
    window_end = win + timedelta(seconds=WINDOW_SECONDS)
    retry_after = max(1, int((window_end - now).total_seconds()))
    allowed = count <= limit
    first_rejection = count == limit + 1
    return RateLimitDecision(
        allowed=allowed,
        limit=limit,
        count=count,
        retry_after_seconds=retry_after,
        first_rejection=first_rejection,
    )


async def enforce(tenant_id: str, bucket: str) -> None:
    """Own-transaction rate-limit gate for a request path.

    Increments the counter, and on the FIRST rejection of the window records
    + emits a `rate_limit.exceeded` event (once per tenant/bucket/window).
    Raises RateLimitExceeded when over the limit; returns None when allowed
    or when the bucket is disabled.
    """
    from app.db import tenant_session  # noqa: PLC0415 — avoid import cycle

    event: dict | None = None
    async with tenant_session(tenant_id) as db:
        decision = await check(db, tenant_id, bucket)
        if decision.allowed:
            return
        if decision.first_rejection:
            event = events_mod.make_event(
                tenant_id=tenant_id,
                type="rate_limit.exceeded",
                payload={
                    "bucket": bucket,
                    "limit_per_min": decision.limit,
                    "retry_after_seconds": decision.retry_after_seconds,
                },
            )
            events_mod.record_events(db, [event])
    if event is not None:
        await events_mod.emit([event])
    raise RateLimitExceeded(decision, bucket)
