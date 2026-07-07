"""Sprint B1 — app-layer isolation attack suite (TENANCY.md §5, B1–B8).

Actively attempts cross-tenant violations against the orchestrator API and
asserts they fail with 404 semantics (no existence oracle) and zero data
leakage. Runs on sqlite (RLS-layer equivalents are in test_isolation_pg.py).
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import sqlalchemy as sa

import app.orchestrator as orch_mod
from app import scheduler as scheduler_mod
from app.api import app
from app.config import get_settings
from app.db import tenant_session
from app.models import Job, Message, Proposal, Session
from tests.conftest import FakeProvider, text_response

VICTIM = "user-victim-1111"
ATTACKER = "user-attacker-2222"

UTC = timezone.utc


@pytest.fixture
def client():
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def patch_provider(monkeypatch):
    def _patch(responses):
        provider = FakeProvider(responses)
        monkeypatch.setattr(orch_mod, "get_provider", lambda *a, **k: provider)
        return provider

    return _patch


async def _victim_session(client, patch_provider) -> str:
    """Provision the victim tenant and create a session with one turn."""
    patch_provider([text_response("victim secret reply")])
    r = await client.post(
        "/v1/agents/chat",
        json={"tenant_id": VICTIM, "agent_id": "personal", "message": "my secret"},
    )
    assert r.status_code == 200
    return r.json()["session_id"]


async def _message_count(tenant: str, sid: str) -> int:
    async with tenant_session(tenant) as db:
        return (
            await db.execute(
                sa.select(sa.func.count())
                .select_from(Message)
                .where(Message.session_id == uuid.UUID(sid))
            )
        ).scalar_one()


# ─── B1: transcript read ─────────────────────────────────────────────────────


async def test_transcript_cross_tenant_404(client, patch_provider):
    async with client:
        sid = await _victim_session(client, patch_provider)
        r = await client.get(
            f"/v1/agents/sessions/{sid}", params={"tenant_id": ATTACKER}
        )
        assert r.status_code == 404
        # indistinguishable from a nonexistent id (no existence oracle)
        r2 = await client.get(
            f"/v1/agents/sessions/{uuid.uuid4()}", params={"tenant_id": ATTACKER}
        )
        assert r2.status_code == 404
        assert r.json().keys() == r2.json().keys() == {"detail"}


# ─── B2: chat hijack of a foreign session ────────────────────────────────────


async def test_chat_with_foreign_session_404_and_no_write(client, patch_provider):
    async with client:
        sid = await _victim_session(client, patch_provider)
        before = await _message_count(VICTIM, sid)
        r = await client.post(
            "/v1/agents/chat",
            json={
                "tenant_id": ATTACKER,
                "agent_id": "personal",
                "message": "inject",
                "session_id": sid,
            },
        )
        assert r.status_code == 404
        assert await _message_count(VICTIM, sid) == before  # nothing appended


# ─── B3: SSE attach to a foreign session ─────────────────────────────────────


async def test_sse_attach_to_foreign_session_error_404(client, patch_provider):
    async with client:
        sid = await _victim_session(client, patch_provider)
        text = ""
        async with client.stream(
            "POST",
            "/v1/agents/chat",
            json={
                "tenant_id": ATTACKER,
                "agent_id": "personal",
                "message": "steal",
                "session_id": sid,
                "stream": True,
            },
        ) as resp:
            assert resp.status_code == 200  # error arrives as an SSE event
            async for chunk in resp.aiter_text():
                text += chunk
        assert "event: error" in text
        assert '"status": 404' in text
        assert "victim secret" not in text
        assert "event: text" not in text  # zero content leaked


# ─── B4: sub-agent jobs ──────────────────────────────────────────────────────


async def test_job_read_cross_tenant_404(client, patch_provider):
    patch_provider([text_response("job done")])
    async with client:
        # provision + queue a job for the victim
        r = await client.post(
            "/v1/agents/subagents",
            json={"tenant_id": VICTIM, "agent_id": "personal", "task": "secret task"},
        )
        assert r.status_code == 202
        job_id = r.json()["job_id"]
        await asyncio.sleep(0.1)  # let the local backend settle
        r2 = await client.get(
            f"/v1/agents/subagents/{job_id}", params={"tenant_id": ATTACKER}
        )
        assert r2.status_code == 404


async def test_job_create_with_foreign_parent_session_404(client, patch_provider):
    async with client:
        sid = await _victim_session(client, patch_provider)
        r = await client.post(
            "/v1/agents/subagents",
            json={
                "tenant_id": ATTACKER,
                "agent_id": "personal",
                "task": "wake their session",
                "session_id": sid,
            },
        )
        assert r.status_code == 404


# ─── B5: schedules ───────────────────────────────────────────────────────────


async def _victim_schedule(client) -> str:
    r = await client.post(
        "/v1/agents/schedules",
        json={
            "tenant_id": VICTIM,
            "agent_id": "personal",
            "name": "victim cron",
            "kind": "cron",
            "cron_expr": "0 9 * * *",
            "message": "secret schedule",
        },
    )
    assert r.status_code == 201
    return r.json()["schedule_id"]


async def test_schedule_crud_cross_tenant_404(client):
    async with client:
        sched_id = await _victim_schedule(client)
        g = await client.get(
            f"/v1/agents/schedules/{sched_id}", params={"tenant_id": ATTACKER}
        )
        assert g.status_code == 404
        p = await client.patch(
            f"/v1/agents/schedules/{sched_id}",
            params={"tenant_id": ATTACKER},
            json={"enabled": False},
        )
        assert p.status_code == 404
        d = await client.delete(
            f"/v1/agents/schedules/{sched_id}", params={"tenant_id": ATTACKER}
        )
        assert d.status_code == 404
        # still alive and enabled for the victim
        ok = await client.get(
            f"/v1/agents/schedules/{sched_id}", params={"tenant_id": VICTIM}
        )
        assert ok.status_code == 200
        assert ok.json()["enabled"] is True


async def test_schedule_create_with_foreign_target_session_404(client, patch_provider):
    async with client:
        sid = await _victim_session(client, patch_provider)
        r = await client.post(
            "/v1/agents/schedules",
            json={
                "tenant_id": ATTACKER,
                "agent_id": "personal",
                "name": "hijack reminder",
                "kind": "at",
                "run_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                "message": "wake their session",
                "session_id": sid,
            },
        )
        assert r.status_code == 404


# ─── B6: approvals notify ────────────────────────────────────────────────────


async def _seed_proposal(tenant: str, approval_id: str) -> uuid.UUID:
    pid = uuid.uuid4()
    async with tenant_session(tenant) as db:
        # tenant + agent must exist (FK-free table, but keep it realistic)
        db.add(
            Proposal(
                proposal_id=pid,
                tenant_id=tenant,
                agent_id="quill",
                tool_name="quill_project_update",
                action="project_update",
                args={},
                idempotency_key=f"sha256:{tenant}:{approval_id}",
                quill_approval_id=approval_id,
                status="pending",
            )
        )
    return pid


def _notify(approval_id: str, tenant: str) -> dict:
    return {
        "approval_id": approval_id,
        "workflow": "agentcloud.project_update",
        "status": "executed",
        "tenant_id": tenant,
    }


async def test_notify_wrong_secret_403(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "APPROVALS_NOTIFY_SECRET", "notify-s")
    async with client:
        r = await client.post(
            "/v1/internal/approvals/notify",
            json=_notify("appr-victim", VICTIM),
            headers={"X-Agent-Secret": "wrong"},
        )
        assert r.status_code == 403
        r2 = await client.post(
            "/v1/internal/approvals/notify", json=_notify("appr-victim", VICTIM)
        )
        assert r2.status_code == 403


async def test_notify_cannot_finalize_foreign_proposal(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "APPROVALS_NOTIFY_SECRET", "notify-s")
    pid = await _seed_proposal(VICTIM, "appr-victim")
    async with client:
        # correct secret, but the approval id is claimed under the wrong tenant
        r = await client.post(
            "/v1/internal/approvals/notify",
            json=_notify("appr-victim", ATTACKER),
            headers={"X-Agent-Secret": "notify-s"},
        )
        assert r.status_code == 200
        assert r.json()["finalized"] is False
    async with tenant_session(VICTIM) as db:
        prop = (
            await db.execute(sa.select(Proposal).where(Proposal.proposal_id == pid))
        ).scalar_one()
        assert prop.status == "pending"  # untouched


# ─── B7: scheduler tick fires into the owning tenant only ───────────────────


async def test_tick_fires_each_schedule_into_its_own_tenant(client, patch_provider):
    patch_provider([text_response("fired A"), text_response("fired B")])
    async with client:
        for tenant in (VICTIM, ATTACKER):
            r = await client.post(
                "/v1/agents/schedules",
                json={
                    "tenant_id": tenant,
                    "agent_id": "personal",
                    "name": f"due-{tenant}",
                    "kind": "at",
                    "run_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                    "message": f"task-for-{tenant}",
                },
            )
            assert r.status_code == 201
    # force both due, then tick once (system path)
    from app.models import Schedule

    for tenant in (VICTIM, ATTACKER):
        async with tenant_session(tenant) as db:
            await db.execute(
                sa.update(Schedule).values(
                    next_run_at=datetime.now(UTC) - timedelta(minutes=5)
                )
            )
    out = await scheduler_mod.tick()
    assert out["fired"] == 2
    await asyncio.sleep(0.2)  # local jobs settle
    # every fired job landed in the namespace of the schedule's owner
    # (sqlite has no RLS, so assert on rows directly — the RLS belt for the
    # same property is test_isolation_pg.py)
    async with tenant_session(VICTIM) as db:
        jobs = (await db.execute(sa.select(Job))).scalars().all()
        assert jobs, "fired jobs must exist"
        for j in jobs:
            assert j.task == f"task-for-{j.tenant_id}", (
                "a schedule fired into a foreign tenant's namespace"
            )
        sessions = (await db.execute(sa.select(Session))).scalars().all()
        by_sid = {s.session_id: s.tenant_id for s in sessions}
        for j in jobs:
            if j.session_id is not None:
                assert by_sid[j.session_id] == j.tenant_id


# ─── B8: list endpoints never leak foreign rows ──────────────────────────────


async def test_lists_never_contain_foreign_rows(client, patch_provider):
    async with client:
        sid = await _victim_session(client, patch_provider)
        # provision the attacker tenant too (fresh, no sessions)
        r = await client.get("/v1/agents", params={"tenant_id": ATTACKER})
        assert r.status_code == 200
        sessions = await client.get(
            "/v1/agents/sessions", params={"tenant_id": ATTACKER}
        )
        assert sessions.status_code == 200
        body = sessions.json()
        assert body["total"] == 0
        assert all(s["session_id"] != sid for s in body["items"])
        scheds = await client.get(
            "/v1/agents/schedules", params={"tenant_id": ATTACKER}
        )
        assert scheds.json()["total"] == 0
