"""A3 sub-agent job tests: lifecycle, wake, budget, events, API, backends."""

import asyncio
import uuid

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app import events as events_mod
from app import jobs as jobs_mod
from app.db import tenant_session
from app.models import AgentDef, Job, Message
from app.orchestrator import chat_turn
from tests.conftest import FakeProvider, text_response

TENANT = "smoke-tenant-jobs"


async def _create(task="do the thing", agent_id="personal", parent=None):
    # dispatch is backgrounded; create with a provider-less queued row, then
    # run explicitly with a scripted provider for determinism.
    created = await jobs_mod.create_job(
        tenant_id=TENANT, agent_id=agent_id, task=task, parent_session_id=parent
    )
    job_id = uuid.UUID(created["job_id"])
    # cancel the auto-dispatched local task; tests drive run_job themselves
    for t in list(jobs_mod._local_tasks):
        t.cancel()
    jobs_mod._local_tasks.clear()
    return job_id


async def test_job_lifecycle_ok_with_result_and_events():
    job_id = await _create()
    provider = FakeProvider([text_response("subagent reply", tin=100, tout=50)])
    final = await jobs_mod.run_job(job_id, TENANT, provider=provider)
    assert final["status"] == "ok"
    assert final["result"]["reply"] == "subagent reply"
    assert final["result"]["budget_exceeded"] is False
    assert final["result"]["usage"]["input_tokens"] == 100
    assert final["session_id"] == final["result"]["session_id"]
    assert final["started_at"] and final["finished_at"]
    types = [e["type"] for e in events_mod.get_bus().published]
    assert types == ["subagent.started", "turn.completed", "subagent.completed"]
    done = events_mod.get_bus().published[-1]
    assert done["payload"]["job_id"] == str(job_id)
    assert done["payload"]["reply_preview"] == "subagent reply"


async def test_job_failure_finalizes_error_and_emits_failed():
    job_id = await _create()

    class ExplodingProvider:
        name = "boom"

        async def complete(self, **kwargs):  # noqa: ARG002
            raise RuntimeError("model exploded")

    final = await jobs_mod.run_job(job_id, TENANT, provider=ExplodingProvider())
    assert final["status"] == "error"
    assert "model exploded" in final["error"]
    types = [e["type"] for e in events_mod.get_bus().published]
    assert types[0] == "subagent.started"
    assert types[-1] == "subagent.failed"


async def test_finalized_job_is_not_rerun():
    job_id = await _create()
    provider = FakeProvider([text_response("once")])
    await jobs_mod.run_job(job_id, TENANT, provider=provider)
    n_events = len(events_mod.get_bus().published)
    again = await jobs_mod.run_job(job_id, TENANT, provider=FakeProvider([]))
    assert again["status"] == "ok"  # unchanged
    assert len(events_mod.get_bus().published) == n_events  # nothing re-emitted


async def test_parent_wake_message_inserted_once():
    parent = await chat_turn(
        tenant_id=TENANT, agent_id="personal", message="hi",
        provider=FakeProvider([text_response("hello")]),
    )
    job_id = await _create(task="research X", parent=parent.session_id)
    await jobs_mod.run_job(
        job_id, TENANT, provider=FakeProvider([text_response("X is 42")])
    )
    async with tenant_session(TENANT) as db:
        rows = (
            await db.execute(
                sa.select(Message)
                .where(
                    Message.tenant_id == TENANT,
                    Message.session_id == parent.session_id,
                )
                .order_by(Message.message_id)
            )
        ).scalars().all()
    wakes = [
        m for m in rows
        if isinstance(m.content, list)
        and m.content
        and "[system wake]" in m.content[0].get("text", "")
    ]
    assert len(wakes) == 1
    text = wakes[0].content[0]["text"]
    assert str(job_id) in text and "completed" in text and "X is 42" in text
    assert wakes[0].role == "user"  # per EVENTS.md wake contract


async def test_job_budget_enforced_same_rows_as_chat():
    # burn budget interactively, then cap it — the job's turn must refuse.
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
    job_id = await _create()
    provider = FakeProvider([text_response("never")])
    final = await jobs_mod.run_job(job_id, TENANT, provider=provider)
    assert final["status"] == "ok"  # a refusal is a completed job, not an error
    assert final["result"]["budget_exceeded"] is True
    assert "budget" in final["result"]["reply"].lower()
    assert provider.calls == 0  # zero model calls
    types = [e["type"] for e in events_mod.get_bus().published]
    assert "budget.exceeded" in types
    done = events_mod.get_bus().published[-1]
    assert done["type"] == "subagent.completed"
    assert done["payload"]["budget_exceeded"] is True


async def test_create_job_unknown_agent_and_bad_parent():
    from app.orchestrator import UnknownAgentError

    with pytest.raises(UnknownAgentError):
        await jobs_mod.create_job(tenant_id=TENANT, agent_id="nope", task="x")
    with pytest.raises(LookupError):
        await jobs_mod.create_job(
            tenant_id=TENANT, agent_id="personal", task="x",
            parent_session_id=uuid.uuid4(),
        )


async def test_get_job_is_tenant_scoped():
    job_id = await _create()
    with pytest.raises(jobs_mod.JobNotFoundError):
        await jobs_mod.get_job("smoke-other-tenant", job_id)


async def test_local_backend_runs_job_end_to_end(monkeypatch):
    """The real dispatch path: create_job spawns an asyncio task that runs it."""
    from app import orchestrator as orch_mod

    provider = FakeProvider([text_response("auto-ran")])
    monkeypatch.setattr(orch_mod, "get_provider", lambda: provider)
    created = await jobs_mod.create_job(
        tenant_id=TENANT, agent_id="personal", task="run yourself"
    )
    job_id = uuid.UUID(created["job_id"])
    for _ in range(100):
        await asyncio.sleep(0.02)
        job = await jobs_mod.get_job(TENANT, job_id)
        if job["status"] not in ("queued", "running"):
            break
    assert job["status"] == "ok"
    assert job["result"]["reply"] == "auto-ran"


class FakeRunClient:
    def __init__(self):
        self.requests = []

    async def run_job(self, request):
        self.requests.append(request)


async def test_cloudrun_backend_launches_execution(monkeypatch):
    client = FakeRunClient()
    monkeypatch.setattr(jobs_mod, "_cloudrun_client_factory", lambda: client)
    monkeypatch.setattr(events_mod.get_settings(), "JOBS_BACKEND", "cloudrun")
    created = await jobs_mod.create_job(
        tenant_id=TENANT, agent_id="personal", task="heavy work"
    )
    assert len(client.requests) == 1
    req = client.requests[0]
    assert req["name"].endswith("/jobs/agentcloud-subagent")
    env = req["overrides"]["container_overrides"][0]["env"]
    assert {"name": "JOB_ID", "value": created["job_id"]} in env
    assert {"name": "JOB_TENANT_ID", "value": TENANT} in env
    # the row exists, queued, for the remote runner to claim
    job = await jobs_mod.get_job(TENANT, uuid.UUID(created["job_id"]))
    assert job["status"] == "queued"


async def test_subagent_api_endpoints(monkeypatch):
    from app import orchestrator as orch_mod
    from app.api import app

    provider_holder = {}

    def fake_get_provider():
        provider_holder.setdefault("p", FakeProvider([text_response("api ran")]))
        return provider_holder["p"]

    monkeypatch.setattr(orch_mod, "get_provider", fake_get_provider)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/agents/subagents",
            json={"tenant_id": TENANT, "agent_id": "personal", "task": "via api"},
        )
        assert r.status_code == 202
        body = r.json()
        job_id = body["job_id"]
        assert body["status"] == "queued"

        for _ in range(100):
            await asyncio.sleep(0.02)
            r2 = await client.get(
                f"/v1/agents/subagents/{job_id}", params={"tenant_id": TENANT}
            )
            assert r2.status_code == 200
            if r2.json()["status"] not in ("queued", "running"):
                break
        assert r2.json()["status"] == "ok"
        assert r2.json()["result"]["reply"] == "api ran"

        # 404s: unknown agent; cross-tenant read; unknown job
        r3 = await client.post(
            "/v1/agents/subagents",
            json={"tenant_id": TENANT, "agent_id": "nope", "task": "x"},
        )
        assert r3.status_code == 404
        r4 = await client.get(
            f"/v1/agents/subagents/{job_id}", params={"tenant_id": "smoke-other"}
        )
        assert r4.status_code == 404


async def test_unknown_backend_raises():
    from app.config import get_settings

    s = get_settings()
    old = s.JOBS_BACKEND
    s.JOBS_BACKEND = "bogus"
    try:
        with pytest.raises(ValueError):
            await jobs_mod._dispatch(uuid.uuid4(), TENANT)
    finally:
        s.JOBS_BACKEND = old
