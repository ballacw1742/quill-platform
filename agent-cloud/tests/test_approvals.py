"""A6 — approval-gated Quill writes (contract: APPROVALS.md)."""

import json
import uuid

import httpx
import pytest
import sqlalchemy as sa

import app.approvals as approvals_mod
import app.orchestrator as orch_mod
from app import events as events_mod
from app.api import app
from app.config import get_settings
from app.db import tenant_session
from app.logging_setup import agent_id_var, session_id_var, tenant_id_var
from app.models import AgentDef, Message, Proposal
from app.orchestrator import chat_turn
from tests.conftest import FakeProvider, text_response, tool_use_response

TENANT = "smoke-approvals"


def _msg_text(m: Message) -> str:
    """Text of a message; tolerant of string content and non-text blocks
    (the tool loop stores tool_result user messages too)."""
    c = m.content
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(b.get("text", "") for b in c if isinstance(b, dict))
    return ""


@pytest.fixture
def client():
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def fake_queue(monkeypatch):
    """Capture the POST /v1/approvals call instead of hitting the network."""
    calls: list[dict] = []

    async def _fake_post(payload):
        calls.append(payload)
        return {"id": f"appr-{len(calls)}", "status": "pending"}

    monkeypatch.setattr(approvals_mod, "_post_approval", _fake_post)
    return calls


@pytest.fixture
def ctx():
    """Set tool contextvars the way stream_turn does before tools run."""
    t1 = tenant_id_var.set(TENANT)
    t2 = agent_id_var.set("quill")
    t3 = session_id_var.set(None)
    yield
    tenant_id_var.reset(t1)
    agent_id_var.reset(t2)
    session_id_var.reset(t3)


async def _provision(session_id_needed: bool = False):
    """First contact + allow-list the write tool. Returns session_id or None."""
    r = await chat_turn(
        tenant_id=TENANT,
        agent_id="quill",
        message="hi",
        provider=FakeProvider([text_response("hello")]),
    )
    async with tenant_session(TENANT) as db:
        agent = (
            await db.execute(
                sa.select(AgentDef).where(
                    AgentDef.tenant_id == TENANT, AgentDef.agent_id == "quill"
                )
            )
        ).scalar_one()
        agent.tools = list(agent.tools) + ["quill_project_update"]
    return r.session_id if session_id_needed else None


# ---------------------------------------------------------------------------
# Tool → proposal
# ---------------------------------------------------------------------------


async def test_write_tool_queues_proposal_and_returns_pending(fake_queue):
    await _provision()
    provider = FakeProvider(
        [
            tool_use_response(
                "quill_project_update",
                {"project_id": "p1", "advance_phase": True, "reasoning": "phase done"},
            ),
            text_response("Queued for approval."),
        ]
    )
    r = await chat_turn(
        tenant_id=TENANT, agent_id="quill", message="advance p1", provider=provider
    )
    assert r.tool_calls == ["quill_project_update"]
    assert len(fake_queue) == 1
    payload = fake_queue[0]
    assert payload["workflow"] == "agentcloud.project_update"
    assert payload["lane"] == 2
    proposed = payload["payload"]["proposed_action"]
    assert proposed["kind"] == "agentcloud_write"
    assert proposed["args"] == {"project_id": "p1", "advance_phase": True}
    assert proposed["tenant_id"] == TENANT
    assert payload["agent_reasoning"] == "phase done"

    async with tenant_session(TENANT) as db:
        prop = (await db.execute(sa.select(Proposal))).scalar_one()
        assert prop.status == "pending"
        assert prop.quill_approval_id == "appr-1"
        assert prop.action == "project_update"
        assert str(prop.session_id) == str(r.session_id)

    # approval.requested on the durable bus
    bus = events_mod.get_bus()
    types = [e["type"] for e in bus.published]
    assert "approval.requested" in types


async def test_validation_error_queues_nothing(fake_queue, ctx):
    from app.tools import run_tool

    out = json.loads(
        await run_tool(
            "quill_project_update",
            {"project_id": "p1", "phase": "not-a-phase"},
            ["quill_project_update"],
        )
    )
    assert "invalid args" in out["error"]
    out = json.loads(
        await run_tool("quill_project_update", {"project_id": "p1"}, ["quill_project_update"])
    )
    assert "invalid args" in out["error"]  # nothing to change
    assert fake_queue == []
    async with tenant_session(TENANT) as db:
        assert (await db.execute(sa.select(Proposal))).first() is None


async def test_write_tool_not_on_allowlist_is_denied(fake_queue, ctx):
    from app.tools import ToolNotAllowedError, run_tool

    with pytest.raises(ToolNotAllowedError):
        await run_tool(
            "quill_project_update",
            {"project_id": "p1", "advance_phase": True},
            ["get_time"],
        )
    assert fake_queue == []


async def test_idempotent_pending_proposal_not_requeued(fake_queue, ctx):
    r1 = await approvals_mod.create_proposal(
        tool_name="quill_project_update",
        action="project_update",
        args={"project_id": "p1", "advance_phase": True},
    )
    r2 = await approvals_mod.create_proposal(
        tool_name="quill_project_update",
        action="project_update",
        args={"project_id": "p1", "advance_phase": True},
    )
    assert len(fake_queue) == 1  # no second queue POST
    assert r2["proposal_id"] == r1["proposal_id"]
    assert "already awaiting" in r2["note"]
    # different args ⇒ new proposal
    r3 = await approvals_mod.create_proposal(
        tool_name="quill_project_update",
        action="project_update",
        args={"project_id": "p2", "advance_phase": True},
    )
    assert len(fake_queue) == 2
    assert r3["proposal_id"] != r1["proposal_id"]


async def test_queue_failure_returns_error_no_row(monkeypatch, ctx):
    async def _boom(payload):
        raise RuntimeError("quill approvals API 503")

    monkeypatch.setattr(approvals_mod, "_post_approval", _boom)
    from app.tools import run_tool

    out = json.loads(
        await run_tool(
            "quill_project_update",
            {"project_id": "p1", "advance_phase": True},
            ["quill_project_update"],
        )
    )
    assert "could not queue" in out["error"]
    async with tenant_session(TENANT) as db:
        assert (await db.execute(sa.select(Proposal))).first() is None


# ---------------------------------------------------------------------------
# Notify endpoint + finalization + wake
# ---------------------------------------------------------------------------


def _notify_body(approval_id: str, status: str = "executed", **kw) -> dict:
    return {
        "approval_id": approval_id,
        "workflow": "agentcloud.project_update",
        "status": status,
        "tenant_id": TENANT,
        **kw,
    }


async def test_notify_403_when_secret_unset(client):
    get_settings().APPROVALS_NOTIFY_SECRET = ""
    async with client:
        r = await client.post(
            "/v1/internal/approvals/notify",
            json=_notify_body("appr-1"),
            headers={"X-Agent-Secret": "anything"},
        )
    assert r.status_code == 403


async def test_notify_finalizes_wakes_and_is_idempotent(
    client, fake_queue, monkeypatch
):
    monkeypatch.setattr(get_settings(), "APPROVALS_NOTIFY_SECRET", "notify-s")
    session_id = await _provision(session_id_needed=True)
    provider = FakeProvider(
        [
            tool_use_response("quill_project_update", {"project_id": "p1", "advance_phase": True}),
            text_response("Queued."),
        ]
    )
    r = await chat_turn(
        tenant_id=TENANT,
        agent_id="quill",
        message="advance p1",
        session_id=session_id,
        provider=provider,
    )
    sid = r.session_id

    async with client:
        # wrong secret → 403
        resp = await client.post(
            "/v1/internal/approvals/notify",
            json=_notify_body("appr-1"),
            headers={"X-Agent-Secret": "wrong"},
        )
        assert resp.status_code == 403
        # non-terminal status → 400
        resp = await client.post(
            "/v1/internal/approvals/notify",
            json=_notify_body("appr-1", status="approved"),
            headers={"X-Agent-Secret": "notify-s"},
        )
        assert resp.status_code == 400
        # executed → finalized
        resp = await client.post(
            "/v1/internal/approvals/notify",
            json=_notify_body("appr-1", external_ref="project:p1"),
            headers={"X-Agent-Secret": "notify-s"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"finalized": True, "status": "executed"}
        # replay (or reconcile racing) → no-op
        resp = await client.post(
            "/v1/internal/approvals/notify",
            json=_notify_body("appr-1", external_ref="project:p1"),
            headers={"X-Agent-Secret": "notify-s"},
        )
        assert resp.json()["finalized"] is False

    async with tenant_session(TENANT) as db:
        prop = (await db.execute(sa.select(Proposal))).scalar_one()
        assert prop.status == "executed"
        assert prop.result["external_ref"] == "project:p1"
        assert prop.result["source"] == "notify"
        assert prop.resolved_at is not None
        wakes = (
            (
                await db.execute(
                    sa.select(Message).where(
                        Message.session_id == sid, Message.role == "user"
                    )
                )
            )
            .scalars()
            .all()
        )
        wake_texts = [
            _msg_text(m) for m in wakes if _msg_text(m).startswith("[system wake]")
        ]
        assert len(wake_texts) == 1  # exactly one wake despite the replay
        assert "APPROVED and executed" in wake_texts[0]
        assert "project:p1" in wake_texts[0]

    bus = events_mod.get_bus()
    resolved = [e for e in bus.published if e["type"] == "approval.resolved"]
    assert len(resolved) == 1
    assert resolved[0]["payload"]["status"] == "executed"


async def test_notify_decline_wake_is_polite(client, fake_queue, monkeypatch):
    monkeypatch.setattr(get_settings(), "APPROVALS_NOTIFY_SECRET", "notify-s")
    session_id = await _provision(session_id_needed=True)
    provider = FakeProvider(
        [
            tool_use_response("quill_project_update", {"project_id": "p1", "advance_phase": True}),
            text_response("Queued."),
        ]
    )
    r = await chat_turn(
        tenant_id=TENANT,
        agent_id="quill",
        message="go",
        session_id=session_id,
        provider=provider,
    )
    async with client:
        resp = await client.post(
            "/v1/internal/approvals/notify",
            json=_notify_body("appr-1", status="rejected"),
            headers={"X-Agent-Secret": "notify-s"},
        )
    assert resp.json() == {"finalized": True, "status": "declined"}
    async with tenant_session(TENANT) as db:
        prop = (await db.execute(sa.select(Proposal))).scalar_one()
        assert prop.status == "declined"
        wake = (
            (
                await db.execute(
                    sa.select(Message).where(
                        Message.session_id == r.session_id, Message.role == "user"
                    )
                )
            )
            .scalars()
            .all()
        )
        texts = [_msg_text(m) for m in wake]
        assert any("DECLINED" in t for t in texts)


async def test_notify_unknown_approval_is_noop(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "APPROVALS_NOTIFY_SECRET", "notify-s")
    async with client:
        r = await client.post(
            "/v1/internal/approvals/notify",
            json=_notify_body("no-such-approval"),
            headers={"X-Agent-Secret": "notify-s"},
        )
    assert r.status_code == 200
    assert r.json()["finalized"] is False


# ---------------------------------------------------------------------------
# Reconcile sweep (belt #2)
# ---------------------------------------------------------------------------


async def _make_stale_pending(ctx_args: dict) -> Proposal:
    async with tenant_session(TENANT) as db:
        prop = Proposal(
            tenant_id=TENANT,
            agent_id="quill",
            session_id=None,
            tool_name="quill_project_update",
            action="project_update",
            args=ctx_args,
            idempotency_key=approvals_mod.idempotency_key(
                TENANT, "quill", "quill_project_update", ctx_args
            ),
            quill_approval_id="appr-stale",
            status="pending",
        )
        db.add(prop)
    # backdate created_at past the reconcile cutoff
    async with tenant_session(TENANT) as db:
        await db.execute(
            sa.update(Proposal).values(
                created_at=approvals_mod._utcnow()
                - __import__("datetime").timedelta(seconds=3600)
            )
        )
    return prop


async def test_reconcile_sweep_finalizes_executed(monkeypatch):
    await _make_stale_pending({"project_id": "p1", "advance_phase": True})

    async def _fake_get(approval_id):
        assert approval_id == "appr-stale"
        return {"id": approval_id, "status": "executed", "external_ref": "project:p1"}

    monkeypatch.setattr(approvals_mod, "_get_quill_approval", _fake_get)
    res = await approvals_mod.reconcile_sweep()
    assert res == {"checked": 1, "resolved": 1}
    async with tenant_session(TENANT) as db:
        prop = (await db.execute(sa.select(Proposal))).scalar_one()
        assert prop.status == "executed"
        assert prop.result["source"] == "reconcile"
    # second sweep: nothing pending
    res = await approvals_mod.reconcile_sweep()
    assert res == {"checked": 0, "resolved": 0}


@pytest.mark.parametrize(
    ("quill_status", "expected"),
    [("rejected", "declined"), ("execution_failed", "failed"), ("cancelled", "expired")],
)
async def test_reconcile_status_mapping(monkeypatch, quill_status, expected):
    await _make_stale_pending({"project_id": "p1", "advance_phase": True})

    async def _fake_get(approval_id):
        return {"id": approval_id, "status": quill_status}

    monkeypatch.setattr(approvals_mod, "_get_quill_approval", _fake_get)
    await approvals_mod.reconcile_sweep()
    async with tenant_session(TENANT) as db:
        prop = (await db.execute(sa.select(Proposal))).scalar_one()
        assert prop.status == expected


async def test_reconcile_leaves_open_statuses_pending(monkeypatch):
    await _make_stale_pending({"project_id": "p1", "advance_phase": True})

    async def _fake_get(approval_id):
        return {"id": approval_id, "status": "approved"}  # not terminal yet

    monkeypatch.setattr(approvals_mod, "_get_quill_approval", _fake_get)
    res = await approvals_mod.reconcile_sweep()
    assert res == {"checked": 1, "resolved": 0}
    async with tenant_session(TENANT) as db:
        prop = (await db.execute(sa.select(Proposal))).scalar_one()
        assert prop.status == "pending"


async def test_reconcile_errors_never_raise(monkeypatch):
    await _make_stale_pending({"project_id": "p1", "advance_phase": True})

    async def _boom(approval_id):
        raise RuntimeError("network down")

    monkeypatch.setattr(approvals_mod, "_get_quill_approval", _boom)
    res = await approvals_mod.reconcile_sweep()  # must not raise
    assert res["resolved"] == 0


async def test_scheduler_tick_runs_sweep(monkeypatch):
    import app.scheduler as scheduler_mod

    await _make_stale_pending({"project_id": "p1", "advance_phase": True})

    async def _fake_get(approval_id):
        return {"id": approval_id, "status": "executed", "external_ref": "project:p1"}

    monkeypatch.setattr(approvals_mod, "_get_quill_approval", _fake_get)
    res = await scheduler_mod.tick()
    assert res["approvals_checked"] == 1
    assert res["approvals_resolved"] == 1


# ---------------------------------------------------------------------------
# Args validation unit coverage
# ---------------------------------------------------------------------------


def test_validate_args_rejects_unknown_keys_and_actions():
    with pytest.raises(approvals_mod.ProposalValidationError):
        approvals_mod.validate_args("project_update", {"project_id": "p", "hax": 1})
    with pytest.raises(approvals_mod.ProposalValidationError):
        approvals_mod.validate_args("drop_tables", {})
    with pytest.raises(approvals_mod.ProposalValidationError):
        approvals_mod.validate_args(
            "project_update", {"project_id": "p", "advance_phase": True, "phase": "design"}
        )
    with pytest.raises(approvals_mod.ProposalValidationError):
        approvals_mod.validate_args(
            "project_milestone_create", {"project_id": "p", "name": "m", "due_date": "soon"}
        )
    with pytest.raises(approvals_mod.ProposalValidationError):
        approvals_mod.validate_args("deal_update", {"deal_id": "d", "probability_pct": 250})
    with pytest.raises(approvals_mod.ProposalValidationError):
        approvals_mod.validate_args("request_update", {"request_id": "r", "status": "processing"})
    ok = approvals_mod.validate_args(
        "deal_update", {"deal_id": "d", "stage": "won", "value_usd": "1000"}
    )
    assert ok == {"deal_id": "d", "stage": "won", "value_usd": 1000.0}
