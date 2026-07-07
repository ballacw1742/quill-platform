"""A4 scheduler tests: next-run math, tick claim/fire through the jobs
machinery, delete_after_run, disabled skip, API CRUD, tick-endpoint auth."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app import events as events_mod
from app import jobs as jobs_mod
from app import scheduler as scheduler_mod
from app.db import tenant_session
from app.models import AgentDef, Job, Schedule
from app.orchestrator import chat_turn
from tests.conftest import FakeProvider, text_response

TENANT = "smoke-tenant-sched"

UTC = timezone.utc


def _past(minutes: int = 5) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=minutes)


def _future(minutes: int = 60) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=minutes)


async def _make_due(schedule_id: str) -> None:
    """Force a schedule's next_run_at into the past (test convenience)."""
    async with tenant_session(TENANT) as db:
        await db.execute(
            sa.update(Schedule)
            .where(Schedule.schedule_id == uuid.UUID(schedule_id))
            .values(next_run_at=_past())
        )


async def _wait_jobs_settled(job_id: str, timeout_s: float = 3.0) -> dict:
    jid = uuid.UUID(job_id)
    for _ in range(int(timeout_s / 0.02)):
        await asyncio.sleep(0.02)
        job = await jobs_mod.get_job(TENANT, jid)
        if job["status"] not in ("queued", "running"):
            return job
    return job


# --------------------------------------------------------------------------
# next-run computation
# --------------------------------------------------------------------------

def test_next_run_cron_respects_timezone():
    # 9am America/New_York in July (EDT, UTC-4) => 13:00 UTC
    after = datetime(2026, 7, 7, 11, 0, tzinfo=UTC)
    nxt = scheduler_mod.compute_next_run(
        kind="cron", cron_expr="0 9 * * *", tz_name="America/New_York", after=after
    )
    assert nxt == datetime(2026, 7, 7, 13, 0, tzinfo=UTC)
    # 9am in January (EST, UTC-5) => 14:00 UTC
    after_winter = datetime(2026, 1, 7, 11, 0, tzinfo=UTC)
    nxt_winter = scheduler_mod.compute_next_run(
        kind="cron", cron_expr="0 9 * * *", tz_name="America/New_York",
        after=after_winter,
    )
    assert nxt_winter == datetime(2026, 1, 7, 14, 0, tzinfo=UTC)


def test_next_run_cron_strictly_after():
    after = datetime(2026, 7, 7, 13, 0, tzinfo=UTC)  # exactly 9am ET
    nxt = scheduler_mod.compute_next_run(
        kind="cron", cron_expr="0 9 * * *", tz_name="America/New_York", after=after
    )
    assert nxt == datetime(2026, 7, 8, 13, 0, tzinfo=UTC)  # next day


def test_next_run_at_one_shot_and_naive_coerced_utc():
    at = datetime(2026, 8, 1, 12, 30)  # naive → treated as UTC
    nxt = scheduler_mod.compute_next_run(kind="at", run_at=at)
    assert nxt == datetime(2026, 8, 1, 12, 30, tzinfo=UTC)


def test_next_run_validation_errors():
    with pytest.raises(scheduler_mod.ScheduleValidationError):
        scheduler_mod.compute_next_run(kind="cron", cron_expr="61 9 * * *")
    with pytest.raises(scheduler_mod.ScheduleValidationError):
        scheduler_mod.compute_next_run(
            kind="cron", cron_expr="0 9 * * *", tz_name="Mars/Olympus"
        )
    with pytest.raises(scheduler_mod.ScheduleValidationError):
        scheduler_mod.compute_next_run(kind="cron", cron_expr=None)
    with pytest.raises(scheduler_mod.ScheduleValidationError):
        scheduler_mod.compute_next_run(kind="at", run_at=None)
    with pytest.raises(scheduler_mod.ScheduleValidationError):
        scheduler_mod.compute_next_run(kind="hourly")


# --------------------------------------------------------------------------
# tick: due execution through the jobs machinery
# --------------------------------------------------------------------------

async def test_tick_fires_due_cron_schedule_through_jobs(monkeypatch):
    from app import orchestrator as orch_mod

    provider = FakeProvider([text_response("reminder sent")])
    monkeypatch.setattr(orch_mod, "get_provider", lambda: provider)

    sched = await scheduler_mod.create_schedule(
        tenant_id=TENANT, agent_id="personal", name="daily standup",
        kind="cron", cron_expr="* * * * *", tz_name="UTC",
        message="remind me about standup",
    )
    await _make_due(sched["schedule_id"])

    res = await scheduler_mod.tick()
    assert res == {"claimed": 1, "fired": 1, "failed": 0}

    after = await scheduler_mod.get_schedule(TENANT, uuid.UUID(sched["schedule_id"]))
    assert after["last_status"] == "fired"
    assert after["last_run_at"] is not None
    assert after["last_job_id"] is not None
    # cron advanced into the future — it stays scheduled
    assert after["next_run_at"] is not None
    assert scheduler_mod._aware_utc(
        datetime.fromisoformat(after["next_run_at"])
    ) > datetime.now(UTC)

    # the fired job is a real agentcloud_jobs row run by the A3 machinery
    job = await _wait_jobs_settled(after["last_job_id"])
    assert job["status"] == "ok"
    assert job["result"]["reply"] == "reminder sent"
    assert job["task"] == "remind me about standup"

    types = [e["type"] for e in events_mod.get_bus().published]
    assert "schedule.fired" in types
    fired = next(e for e in events_mod.get_bus().published if e["type"] == "schedule.fired")
    assert fired["tenant_id"] == TENANT
    assert fired["payload"]["schedule_id"] == sched["schedule_id"]
    assert fired["payload"]["job_id"] == after["last_job_id"]


async def test_tick_one_shot_fires_once_and_keeps_row(monkeypatch):
    from app import orchestrator as orch_mod

    monkeypatch.setattr(
        orch_mod, "get_provider", lambda: FakeProvider([text_response("done")])
    )
    sched = await scheduler_mod.create_schedule(
        tenant_id=TENANT, agent_id="personal", name="one shot",
        kind="at", run_at=_past(), message="fire once",
    )
    res = await scheduler_mod.tick()
    assert res["fired"] == 1
    after = await scheduler_mod.get_schedule(TENANT, uuid.UUID(sched["schedule_id"]))
    assert after["next_run_at"] is None  # one-shot: never re-fires
    assert after["last_status"] == "fired"
    # a second tick claims nothing
    res2 = await scheduler_mod.tick()
    assert res2 == {"claimed": 0, "fired": 0, "failed": 0}


async def test_tick_delete_after_run_removes_one_shot(monkeypatch):
    from app import orchestrator as orch_mod

    monkeypatch.setattr(
        orch_mod, "get_provider", lambda: FakeProvider([text_response("done")])
    )
    sched = await scheduler_mod.create_schedule(
        tenant_id=TENANT, agent_id="personal", name="ephemeral reminder",
        kind="at", run_at=_past(), message="remind then vanish",
        delete_after_run=True,
    )
    res = await scheduler_mod.tick()
    assert res["fired"] == 1
    with pytest.raises(scheduler_mod.ScheduleNotFoundError):
        await scheduler_mod.get_schedule(TENANT, uuid.UUID(sched["schedule_id"]))
    # …but the fired job exists and the schedule.fired event was recorded
    types = [e["type"] for e in events_mod.get_bus().published]
    assert "schedule.fired" in types


async def test_tick_skips_disabled_and_future_schedules():
    sched = await scheduler_mod.create_schedule(
        tenant_id=TENANT, agent_id="personal", name="disabled",
        kind="at", run_at=_past(), message="never", enabled=False,
    )
    await scheduler_mod.create_schedule(
        tenant_id=TENANT, agent_id="personal", name="future",
        kind="at", run_at=_future(), message="later",
    )
    res = await scheduler_mod.tick()
    assert res == {"claimed": 0, "fired": 0, "failed": 0}
    after = await scheduler_mod.get_schedule(TENANT, uuid.UUID(sched["schedule_id"]))
    assert after["last_run_at"] is None


async def test_tick_budget_refusal_flows_through_jobs(monkeypatch):
    """A budget-capped agent still 'fires' — the job completes as a polite
    refusal (A3 semantics), with zero model calls."""
    from app import orchestrator as orch_mod

    await chat_turn(
        tenant_id=TENANT, agent_id="personal", message="hi",
        provider=FakeProvider([text_response("ok", tin=1000, tout=1000)]),
    )
    async with tenant_session(TENANT) as db:
        await db.execute(
            sa.update(AgentDef)
            .where(AgentDef.tenant_id == TENANT, AgentDef.agent_id == "personal")
            .values(budget_monthly_usd=0.000001)
        )
    provider = FakeProvider([text_response("never")])
    monkeypatch.setattr(orch_mod, "get_provider", lambda: provider)

    sched = await scheduler_mod.create_schedule(
        tenant_id=TENANT, agent_id="personal", name="capped",
        kind="at", run_at=_past(), message="expensive reminder",
    )
    res = await scheduler_mod.tick()
    assert res["fired"] == 1
    after = await scheduler_mod.get_schedule(TENANT, uuid.UUID(sched["schedule_id"]))
    job = await _wait_jobs_settled(after["last_job_id"])
    assert job["status"] == "ok"
    assert job["result"]["budget_exceeded"] is True
    assert provider.calls == 0
    types = [e["type"] for e in events_mod.get_bus().published]
    assert "schedule.fired" in types and "budget.exceeded" in types


async def test_tick_failure_recorded_never_raises():
    """A schedule pointing at a nonexistent agent fails cleanly: last_status
    error + schedule.failed, and the tick loop survives."""
    sid = uuid.uuid4()
    async with tenant_session(TENANT) as db:
        db.add(
            Schedule(
                schedule_id=sid, tenant_id=TENANT, agent_id="ghost",
                name="broken", kind="at", run_at=_past(),
                payload={"message": "boom"}, next_run_at=_past(),
            )
        )
    res = await scheduler_mod.tick()
    assert res == {"claimed": 1, "fired": 0, "failed": 1}
    after = await scheduler_mod.get_schedule(TENANT, sid)
    assert after["last_status"].startswith("error:")
    assert after["next_run_at"] is None  # claimed one-shot is not retried
    failed = [e for e in events_mod.get_bus().published if e["type"] == "schedule.failed"]
    assert len(failed) == 1
    assert failed[0]["payload"]["schedule_id"] == str(sid)


async def test_tick_wakes_target_session(monkeypatch):
    """Reminder delivery: a schedule with session_id produces a wake in that
    session (EVENTS.md wake contract via the jobs machinery)."""
    from app import orchestrator as orch_mod
    from app.models import Message

    parent = await chat_turn(
        tenant_id=TENANT, agent_id="personal", message="hello",
        provider=FakeProvider([text_response("hi")]),
    )
    monkeypatch.setattr(
        orch_mod, "get_provider",
        lambda: FakeProvider([text_response("Reminder: standup at 9!")]),
    )
    sched = await scheduler_mod.create_schedule(
        tenant_id=TENANT, agent_id="personal", name="wake me",
        kind="at", run_at=_past(), message="remind about standup",
        session_id=parent.session_id,
    )
    res = await scheduler_mod.tick()
    assert res["fired"] == 1
    after = await scheduler_mod.get_schedule(TENANT, uuid.UUID(sched["schedule_id"]))
    await _wait_jobs_settled(after["last_job_id"])
    async with tenant_session(TENANT) as db:
        rows = (
            await db.execute(
                sa.select(Message).where(
                    Message.tenant_id == TENANT,
                    Message.session_id == parent.session_id,
                )
            )
        ).scalars().all()
    wakes = [
        m for m in rows
        if isinstance(m.content, list) and m.content
        and "[system wake]" in m.content[0].get("text", "")
    ]
    assert len(wakes) == 1
    assert "Reminder: standup at 9!" in wakes[0].content[0]["text"]


async def test_loop_backend_start_stop_ticks(monkeypatch):
    """The in-process loop backend actually ticks and shuts down cleanly."""
    calls = []

    async def fake_tick(now=None):
        calls.append(1)
        return {"claimed": 0, "fired": 0, "failed": 0}

    monkeypatch.setattr(scheduler_mod, "tick", fake_tick)
    monkeypatch.setattr(
        scheduler_mod.get_settings(), "SCHEDULER_TICK_SECONDS", 0.01
    )
    try:
        scheduler_mod.start_loop()
        await asyncio.sleep(0.1)
    finally:
        await scheduler_mod.stop_loop()
        monkeypatch.setattr(
            scheduler_mod.get_settings(), "SCHEDULER_TICK_SECONDS", 30
        )
    assert len(calls) >= 2
    assert scheduler_mod._loop_task is None


# --------------------------------------------------------------------------
# API CRUD + tick endpoint auth
# --------------------------------------------------------------------------

@pytest.fixture
async def client():
    from app.api import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_schedule_api_crud_and_cross_tenant_404(client):
    body = {
        "tenant_id": TENANT, "agent_id": "personal", "name": "morning brief",
        "kind": "cron", "cron_expr": "0 8 * * *", "timezone": "America/New_York",
        "message": "send the morning brief",
    }
    r = await client.post("/v1/agents/schedules", json=body)
    assert r.status_code == 201
    created = r.json()
    sid = created["schedule_id"]
    assert created["kind"] == "cron"
    assert created["timezone"] == "America/New_York"
    assert created["enabled"] is True
    assert created["next_run_at"] is not None
    assert created["payload"]["message"] == "send the morning brief"

    # list (standard envelope)
    r = await client.get("/v1/agents/schedules", params={"tenant_id": TENANT})
    assert r.status_code == 200
    listing = r.json()
    assert listing["total"] == 1
    assert listing["items"][0]["schedule_id"] == sid
    assert {"items", "total", "limit", "offset"} <= set(listing.keys())

    # get
    r = await client.get(f"/v1/agents/schedules/{sid}", params={"tenant_id": TENANT})
    assert r.status_code == 200

    # cross-tenant: list is empty, get/patch/delete are 404
    r = await client.get("/v1/agents/schedules", params={"tenant_id": "smoke-other"})
    assert r.json()["total"] == 0
    r = await client.get(f"/v1/agents/schedules/{sid}", params={"tenant_id": "smoke-other"})
    assert r.status_code == 404
    assert "detail" in r.json()
    r = await client.patch(
        f"/v1/agents/schedules/{sid}", params={"tenant_id": "smoke-other"},
        json={"enabled": False},
    )
    assert r.status_code == 404
    r = await client.delete(
        f"/v1/agents/schedules/{sid}", params={"tenant_id": "smoke-other"}
    )
    assert r.status_code == 404

    # patch: disable, then re-enable with a new cron recomputes next_run_at
    r = await client.patch(
        f"/v1/agents/schedules/{sid}", params={"tenant_id": TENANT},
        json={"enabled": False},
    )
    assert r.status_code == 200 and r.json()["enabled"] is False
    r = await client.patch(
        f"/v1/agents/schedules/{sid}", params={"tenant_id": TENANT},
        json={"enabled": True, "cron_expr": "30 18 * * *"},
    )
    assert r.status_code == 200
    assert r.json()["cron_expr"] == "30 18 * * *"
    assert r.json()["next_run_at"] is not None

    # delete
    r = await client.delete(f"/v1/agents/schedules/{sid}", params={"tenant_id": TENANT})
    assert r.status_code == 204
    r = await client.get(f"/v1/agents/schedules/{sid}", params={"tenant_id": TENANT})
    assert r.status_code == 404


async def test_schedule_api_validation_and_agent_404(client):
    base = {"tenant_id": TENANT, "agent_id": "personal", "name": "x", "message": "m"}
    r = await client.post(
        "/v1/agents/schedules", json={**base, "kind": "cron", "cron_expr": "not a cron"}
    )
    assert r.status_code == 400 and "detail" in r.json()
    r = await client.post(
        "/v1/agents/schedules",
        json={**base, "kind": "cron", "cron_expr": "0 9 * * *", "timezone": "Nope/Nope"},
    )
    assert r.status_code == 400
    r = await client.post("/v1/agents/schedules", json={**base, "kind": "at"})
    assert r.status_code == 400  # run_at required
    r = await client.post(
        "/v1/agents/schedules",
        json={**base, "agent_id": "ghost", "kind": "cron", "cron_expr": "0 9 * * *"},
    )
    assert r.status_code == 404  # unknown agent, same semantics as subagents
    r = await client.post(
        "/v1/agents/schedules",
        json={**base, "kind": "at", "run_at": "2030-01-01T00:00:00Z",
              "session_id": str(uuid.uuid4())},
    )
    assert r.status_code == 404  # unknown target session


async def test_tick_endpoint_auth(client, monkeypatch):
    s = scheduler_mod.get_settings()
    # secret unset ⇒ endpoint disabled
    monkeypatch.setattr(s, "SCHEDULER_TICK_SECRET", "")
    r = await client.post("/v1/internal/scheduler/tick")
    assert r.status_code == 403
    # wrong secret
    monkeypatch.setattr(s, "SCHEDULER_TICK_SECRET", "s3cret")
    r = await client.post(
        "/v1/internal/scheduler/tick", headers={"X-Agent-Secret": "wrong"}
    )
    assert r.status_code == 403
    # right secret ⇒ a real (empty) tick runs
    r = await client.post(
        "/v1/internal/scheduler/tick", headers={"X-Agent-Secret": "s3cret"}
    )
    assert r.status_code == 200
    assert r.json() == {"claimed": 0, "fired": 0, "failed": 0}
