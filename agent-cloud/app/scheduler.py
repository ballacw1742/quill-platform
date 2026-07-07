"""Per-tenant schedules — cron + one-shot reminders (A4; design doc §2
"Cloud Scheduler (cron/reminders per tenant)").

A schedule is a row in `agentcloud_schedules` (RLS'd like every
agentcloud_* table). When due, it fires **through the A3 jobs machinery**
(`jobs.create_job` → an `agentcloud_jobs` row → a normal orchestrator turn
in a fresh sub-session), so budget metering, events, tool allow-lists and
the polite budget refusal all apply unchanged. If the schedule has a target
`session_id`, it is passed as the job's `parent_session_id`, so the
completed turn wakes that session per the EVENTS.md wake contract — that is
the reminder delivery path.

Timing: `next_run_at` is always stored in UTC. Cron expressions are
evaluated with croniter in the schedule's IANA timezone, then converted.

Claiming (safe for multiple orchestrator instances): the tick does
`SELECT … WHERE enabled AND next_run_at <= now() ORDER BY next_run_at
LIMIT n FOR UPDATE SKIP LOCKED` and advances `next_run_at` (cron → next
occurrence; one-shot → NULL) **inside the same locked transaction**, so a
concurrent tick can never double-claim a schedule. The claim scans across
tenants, so it runs under the admin RLS policy (`admin_session`) — a
system/maintenance path, same policy the CLI uses; per-schedule execution
then goes back through tenant-scoped sessions.

Tick delivery is config-gated like every other backend
(`SCHEDULER_BACKEND`):
  - "loop": in-process asyncio task ticking every SCHEDULER_TICK_SECONDS
    (default 30) — dev/local + acceptable single-instance default.
  - "cloudscheduler": no in-process loop; a Cloud Scheduler HTTP job POSTs
    /v1/internal/scheduler/tick (X-Agent-Secret = SCHEDULER_TICK_SECRET)
    every minute. One-time gcloud setup in README; app code creates no GCP
    resources.

A tick never raises: every failure is recorded on the schedule row
(`last_status`) and emitted as `schedule.failed` (EVENTS.md).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from croniter import croniter

from app import events as events_mod
from app import jobs as jobs_mod
from app.config import get_settings
from app.db import admin_session, tenant_session
from app.models import Schedule, Session

log = logging.getLogger("agentcloud.scheduler")

SCHEDULE_KINDS = ("at", "cron")


class ScheduleNotFoundError(LookupError):
    pass


class ScheduleValidationError(ValueError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(dt: datetime) -> datetime:
    """Coerce to tz-aware UTC (sqlite reads back naive datetimes)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def validate_timing(
    kind: str, cron_expr: str | None, tz_name: str, run_at: datetime | None
) -> None:
    """Raise ScheduleValidationError on any bad timing spec (API 400s)."""
    if kind not in SCHEDULE_KINDS:
        raise ScheduleValidationError(f"kind must be one of {SCHEDULE_KINDS}, got {kind!r}")
    try:
        ZoneInfo(tz_name or "UTC")
    except Exception as exc:  # noqa: BLE001 — ZoneInfoNotFoundError et al.
        raise ScheduleValidationError(f"unknown IANA timezone {tz_name!r}") from exc
    if kind == "cron":
        if not cron_expr:
            raise ScheduleValidationError("kind='cron' requires cron_expr")
        if not croniter.is_valid(cron_expr):
            raise ScheduleValidationError(f"invalid cron expression {cron_expr!r}")
    else:  # at
        if run_at is None:
            raise ScheduleValidationError("kind='at' requires run_at")


def compute_next_run(
    *,
    kind: str,
    cron_expr: str | None = None,
    tz_name: str = "UTC",
    run_at: datetime | None = None,
    after: datetime | None = None,
) -> datetime | None:
    """Next fire time in UTC. 'at' → run_at; 'cron' → next occurrence of
    cron_expr in tz_name strictly after `after` (default: now)."""
    validate_timing(kind, cron_expr, tz_name, run_at)
    if kind == "at":
        return _aware_utc(run_at)  # type: ignore[arg-type]  # validated above
    after = _aware_utc(after or _utcnow())
    base = after.astimezone(ZoneInfo(tz_name or "UTC"))
    nxt = croniter(cron_expr, base).get_next(datetime)
    return nxt.astimezone(timezone.utc)


def schedule_dict(row: Schedule) -> dict[str, Any]:
    return {
        "schedule_id": str(row.schedule_id),
        "tenant_id": row.tenant_id,
        "agent_id": row.agent_id,
        "name": row.name,
        "kind": row.kind,
        "cron_expr": row.cron_expr,
        "timezone": row.timezone,
        "run_at": str(row.run_at) if row.run_at else None,
        "payload": row.payload,
        "session_id": str(row.session_id) if row.session_id else None,
        "enabled": row.enabled,
        "delete_after_run": row.delete_after_run,
        "next_run_at": str(row.next_run_at) if row.next_run_at else None,
        "last_run_at": str(row.last_run_at) if row.last_run_at else None,
        "last_status": row.last_status,
        "last_job_id": str(row.last_job_id) if row.last_job_id else None,
        "created_at": str(row.created_at),
        "updated_at": str(row.updated_at),
    }


async def _validate_agent_and_session(
    db, tenant_id: str, agent_id: str, session_id: uuid.UUID | None
) -> None:
    """Same provisioning + 404/403 semantics as jobs.create_job."""
    from app.models import AgentDef, Tenant  # noqa: PLC0415
    from app.orchestrator import (  # noqa: PLC0415 — avoid import cycle
        AgentDisabledError,
        UnknownAgentError,
        _insert_ignore,
    )
    from app.seeds import SEED_AGENTS, seed_model_for_tenant  # noqa: PLC0415

    s = get_settings()
    dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
    await db.execute(_insert_ignore(Tenant, {"tenant_id": tenant_id}, dialect))
    seed_model = seed_model_for_tenant(tenant_id)
    for seed in SEED_AGENTS:
        await db.execute(
            _insert_ignore(
                AgentDef,
                {
                    "tenant_id": tenant_id,
                    "agent_id": seed.agent_id,
                    "system_prompt": seed.system_prompt.format(tenant_id=tenant_id),
                    "model": seed_model,
                    "tools": list(seed.tools),
                    "budget_monthly_usd": s.DEFAULT_BUDGET_MONTHLY_USD,
                    "enabled": True,
                    "memory_policy": seed.memory_policy,
                },
                dialect,
            )
        )
    agent = (
        await db.execute(
            sa.select(AgentDef).where(
                AgentDef.tenant_id == tenant_id, AgentDef.agent_id == agent_id
            )
        )
    ).scalar_one_or_none()
    if agent is None:
        raise UnknownAgentError(f"agent {agent_id!r} is not defined for this tenant")
    if not agent.enabled:
        raise AgentDisabledError(f"agent {agent_id!r} is disabled")
    if session_id is not None:
        sess = (
            await db.execute(
                sa.select(Session.session_id).where(
                    Session.session_id == session_id,
                    Session.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if sess is None:
            raise ScheduleNotFoundError("target session not found for this tenant")


# --------------------------------------------------------------------------
# CRUD (tenant-scoped; API surface in app/api.py)
# --------------------------------------------------------------------------

async def create_schedule(
    *,
    tenant_id: str,
    agent_id: str,
    name: str,
    kind: str,
    cron_expr: str | None = None,
    tz_name: str = "UTC",
    run_at: datetime | None = None,
    message: str,
    session_id: uuid.UUID | None = None,
    enabled: bool = True,
    delete_after_run: bool = False,
) -> dict[str, Any]:
    s = get_settings()
    message = (message or "").strip()[: s.SCHEDULE_MESSAGE_MAX_CHARS]
    if not message:
        raise ScheduleValidationError("message must be non-empty")
    next_run = compute_next_run(
        kind=kind, cron_expr=cron_expr, tz_name=tz_name, run_at=run_at
    )
    row = Schedule(
        schedule_id=uuid.uuid4(),
        tenant_id=tenant_id,
        agent_id=agent_id,
        name=(name or "").strip()[:200] or "unnamed",
        kind=kind,
        cron_expr=cron_expr if kind == "cron" else None,
        timezone=tz_name or "UTC",
        run_at=_aware_utc(run_at) if run_at else None,
        payload={"message": message},
        session_id=session_id,
        enabled=enabled,
        delete_after_run=delete_after_run,
        next_run_at=next_run,  # kept even when disabled (tick checks enabled)
    )
    async with tenant_session(tenant_id) as db:
        await _validate_agent_and_session(db, tenant_id, agent_id, session_id)
        db.add(row)
    return schedule_dict(row)


async def list_schedules(
    tenant_id: str, *, limit: int = 100, offset: int = 0
) -> dict[str, Any]:
    async with tenant_session(tenant_id) as db:
        total = (
            await db.execute(
                sa.select(sa.func.count())
                .select_from(Schedule)
                .where(Schedule.tenant_id == tenant_id)
            )
        ).scalar_one()
        rows = (
            (
                await db.execute(
                    sa.select(Schedule)
                    .where(Schedule.tenant_id == tenant_id)
                    .order_by(Schedule.created_at, Schedule.schedule_id)
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return {
            "items": [schedule_dict(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


async def get_schedule(tenant_id: str, schedule_id: uuid.UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as db:
        row = (
            await db.execute(
                sa.select(Schedule).where(
                    Schedule.schedule_id == schedule_id,
                    Schedule.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise ScheduleNotFoundError("schedule not found for this tenant")
        return schedule_dict(row)


_UNSET = object()


async def update_schedule(
    tenant_id: str,
    schedule_id: uuid.UUID,
    *,
    name: Any = _UNSET,
    kind: Any = _UNSET,
    cron_expr: Any = _UNSET,
    tz_name: Any = _UNSET,
    run_at: Any = _UNSET,
    message: Any = _UNSET,
    enabled: Any = _UNSET,
    delete_after_run: Any = _UNSET,
) -> dict[str, Any]:
    """PATCH semantics: only provided fields change. Any timing-field change
    (kind/cron_expr/timezone/run_at) or re-enable recomputes next_run_at."""
    s = get_settings()
    async with tenant_session(tenant_id) as db:
        row = (
            await db.execute(
                sa.select(Schedule).where(
                    Schedule.schedule_id == schedule_id,
                    Schedule.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise ScheduleNotFoundError("schedule not found for this tenant")

        timing_changed = False
        if name is not _UNSET:
            row.name = (str(name) or "").strip()[:200] or row.name
        if kind is not _UNSET:
            row.kind = kind
            timing_changed = True
        if cron_expr is not _UNSET:
            row.cron_expr = cron_expr
            timing_changed = True
        if tz_name is not _UNSET:
            row.timezone = tz_name or "UTC"
            timing_changed = True
        if run_at is not _UNSET:
            row.run_at = _aware_utc(run_at) if run_at else None
            timing_changed = True
        if message is not _UNSET:
            msg = (str(message) or "").strip()[: s.SCHEDULE_MESSAGE_MAX_CHARS]
            if not msg:
                raise ScheduleValidationError("message must be non-empty")
            row.payload = {**(row.payload or {}), "message": msg}
        if delete_after_run is not _UNSET:
            row.delete_after_run = bool(delete_after_run)
        re_enabled = False
        if enabled is not _UNSET:
            re_enabled = bool(enabled) and not row.enabled
            row.enabled = bool(enabled)

        if timing_changed or re_enabled:
            row.next_run_at = compute_next_run(
                kind=row.kind,
                cron_expr=row.cron_expr,
                tz_name=row.timezone,
                run_at=row.run_at,
            )
        row.updated_at = _utcnow()
        return schedule_dict(row)


async def delete_schedule(tenant_id: str, schedule_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as db:
        row = (
            await db.execute(
                sa.select(Schedule).where(
                    Schedule.schedule_id == schedule_id,
                    Schedule.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise ScheduleNotFoundError("schedule not found for this tenant")
        await db.delete(row)


# --------------------------------------------------------------------------
# Tick: claim due schedules, fire them through the jobs machinery
# --------------------------------------------------------------------------

async def _claim_due(now: datetime) -> list[dict[str, Any]]:
    """Claim up to SCHEDULER_MAX_PER_TICK due schedules and advance their
    next_run_at inside one locked transaction (FOR UPDATE SKIP LOCKED on
    Postgres — safe for concurrent orchestrator instances)."""
    s = get_settings()
    claimed: list[dict[str, Any]] = []
    async with admin_session() as db:
        stmt = (
            sa.select(Schedule)
            .where(
                Schedule.enabled.is_(True),
                Schedule.next_run_at.is_not(None),
                Schedule.next_run_at <= now,
            )
            .order_by(Schedule.next_run_at)
            .limit(s.SCHEDULER_MAX_PER_TICK)
        )
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        rows = (await db.execute(stmt)).scalars().all()
        for row in rows:
            if row.kind == "cron":
                try:
                    row.next_run_at = compute_next_run(
                        kind="cron",
                        cron_expr=row.cron_expr,
                        tz_name=row.timezone,
                        after=now,
                    )
                except ScheduleValidationError:
                    # corrupt timing spec: park it (never reclaim-loop)
                    row.next_run_at = None
                    row.last_status = "error: invalid timing spec"
            else:
                row.next_run_at = None  # one-shot: fires exactly once
            row.last_run_at = now
            row.updated_at = now
            claimed.append(
                {
                    "schedule_id": row.schedule_id,
                    "tenant_id": row.tenant_id,
                    "agent_id": row.agent_id,
                    "name": row.name,
                    "kind": row.kind,
                    "message": (row.payload or {}).get("message") or row.name,
                    "session_id": row.session_id,
                    "delete_after_run": row.delete_after_run,
                }
            )
    return claimed


async def _fire_one(item: dict[str, Any]) -> bool:
    """Fire one claimed schedule as a sub-agent job. Returns True on success.
    Never raises — failures land in last_status + schedule.failed."""
    tenant_id = item["tenant_id"]
    schedule_id = item["schedule_id"]
    try:
        created = await jobs_mod.create_job(
            tenant_id=tenant_id,
            agent_id=item["agent_id"],
            task=item["message"],
            parent_session_id=item["session_id"],
        )
        job_id = uuid.UUID(created["job_id"])
        fired_ev = events_mod.make_event(
            tenant_id=tenant_id,
            agent_id=item["agent_id"],
            session_id=item["session_id"],
            type="schedule.fired",
            payload={
                "schedule_id": str(schedule_id),
                "name": item["name"],
                "kind": item["kind"],
                "job_id": str(job_id),
            },
        )
        async with tenant_session(tenant_id) as db:
            events_mod.record_events(db, [fired_ev])
            if item["kind"] == "at" and item["delete_after_run"]:
                await db.execute(
                    sa.delete(Schedule).where(
                        Schedule.schedule_id == schedule_id,
                        Schedule.tenant_id == tenant_id,
                    )
                )
            else:
                await db.execute(
                    sa.update(Schedule)
                    .where(
                        Schedule.schedule_id == schedule_id,
                        Schedule.tenant_id == tenant_id,
                    )
                    .values(
                        last_status="fired",
                        last_job_id=job_id,
                        updated_at=_utcnow(),
                    )
                )
        await events_mod.emit([fired_ev])
        return True
    except Exception as exc:  # noqa: BLE001 — the tick loop must never crash
        error_text = f"{type(exc).__name__}: {exc}"
        log.exception("schedule %s failed to fire", schedule_id)
        failed_ev = events_mod.make_event(
            tenant_id=tenant_id,
            agent_id=item["agent_id"],
            session_id=item["session_id"],
            type="schedule.failed",
            payload={
                "schedule_id": str(schedule_id),
                "name": item["name"],
                "error": error_text,
            },
        )
        try:
            async with tenant_session(tenant_id) as db:
                events_mod.record_events(db, [failed_ev])
                await db.execute(
                    sa.update(Schedule)
                    .where(
                        Schedule.schedule_id == schedule_id,
                        Schedule.tenant_id == tenant_id,
                    )
                    .values(
                        last_status=f"error: {error_text}"[:500],
                        updated_at=_utcnow(),
                    )
                )
            await events_mod.emit([failed_ev])
        except Exception:  # noqa: BLE001 — even bookkeeping must not crash the tick
            log.exception("schedule %s failure bookkeeping failed", schedule_id)
        return False


async def tick(now: datetime | None = None) -> dict[str, int]:
    """One scheduler pass: claim due schedules, fire each one. Never raises
    per-schedule errors; returns counters for logging/response bodies."""
    now = _aware_utc(now or _utcnow())
    claimed = await _claim_due(now)
    fired = 0
    failed = 0
    for item in claimed:
        if await _fire_one(item):
            fired += 1
        else:
            failed += 1
    if claimed:
        log.info(
            "scheduler tick",
            extra={
                "extra_fields": {
                    "claimed": len(claimed),
                    "fired": fired,
                    "failed": failed,
                }
            },
        )
    return {"claimed": len(claimed), "fired": fired, "failed": failed}


# --------------------------------------------------------------------------
# Loop backend (SCHEDULER_BACKEND=loop)
# --------------------------------------------------------------------------

_loop_task: asyncio.Task | None = None


async def _tick_forever() -> None:
    s = get_settings()
    while True:
        try:
            await tick()
        except Exception:  # noqa: BLE001 — the loop survives any tick error
            log.exception("scheduler tick pass failed")
        await asyncio.sleep(s.SCHEDULER_TICK_SECONDS)


def start_loop() -> None:
    """Start the in-process tick loop (idempotent)."""
    global _loop_task
    if _loop_task is None or _loop_task.done():
        _loop_task = asyncio.get_running_loop().create_task(_tick_forever())
        log.info(
            "scheduler loop started",
            extra={
                "extra_fields": {"tick_seconds": get_settings().SCHEDULER_TICK_SECONDS}
            },
        )


async def stop_loop() -> None:
    global _loop_task
    if _loop_task is not None:
        _loop_task.cancel()
        try:
            await _loop_task
        except asyncio.CancelledError:
            pass
        _loop_task = None
