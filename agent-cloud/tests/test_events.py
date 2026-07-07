"""A3 event contract tests (inline bus + durable rows). Contract: EVENTS.md."""

import json
import uuid

import pytest
import sqlalchemy as sa

from app import events as events_mod
from app.db import tenant_session
from app.models import AgentDef, EventRow
from app.orchestrator import chat_turn
from tests.conftest import FakeProvider, text_response, tool_use_response

TENANT = "smoke-tenant-events"

ENVELOPE_KEYS = {
    "event_id", "tenant_id", "agent_id", "session_id", "type", "ts", "payload", "attempt",
}


def _bus() -> events_mod.InlineBus:
    bus = events_mod.get_bus()
    assert isinstance(bus, events_mod.InlineBus)
    return bus


async def _rows(tenant: str) -> list[EventRow]:
    async with tenant_session(tenant) as db:
        return list(
            (
                await db.execute(
                    sa.select(EventRow)
                    .where(EventRow.tenant_id == tenant)
                    .order_by(EventRow.created_at)
                )
            ).scalars()
        )


def test_make_event_matches_contract():
    ev = events_mod.make_event(
        tenant_id=TENANT, agent_id="personal", type="turn.completed", payload={"x": 1}
    )
    assert set(ev.keys()) == ENVELOPE_KEYS
    assert ev["attempt"] == 1
    uuid.UUID(ev["event_id"])  # valid uuid
    assert ev["session_id"] is None


def test_make_event_refuses_uncontracted_type():
    with pytest.raises(ValueError):
        events_mod.make_event(tenant_id=TENANT, type="made.up", payload={})


async def test_turn_emits_completed_event_and_durable_row():
    provider = FakeProvider([text_response("hi", tin=100, tout=50)])
    result = await chat_turn(
        tenant_id=TENANT, agent_id="personal", message="hello", provider=provider
    )
    pub = _bus().published
    assert [e["type"] for e in pub] == ["turn.completed"]
    ev = pub[0]
    assert set(ev.keys()) == ENVELOPE_KEYS
    assert ev["tenant_id"] == TENANT
    assert ev["agent_id"] == "personal"
    assert ev["session_id"] == str(result.session_id)
    assert ev["payload"]["input_tokens"] == 100
    assert ev["payload"]["output_tokens"] == 50
    assert ev["payload"]["budget_exceeded"] is False
    assert abs(ev["payload"]["cost_usd"] - result.cost_usd) < 1e-9
    # durable row (same envelope, keyed by event_id)
    rows = await _rows(TENANT)
    assert len(rows) == 1
    assert str(rows[0].event_id) == ev["event_id"]
    assert rows[0].type == "turn.completed"
    assert rows[0].payload["tool_calls"] == []


async def test_tool_execution_emits_tool_executed():
    provider = FakeProvider(
        [tool_use_response("get_time"), text_response("done")]
    )
    await chat_turn(
        tenant_id=TENANT, agent_id="personal", message="time?", provider=provider
    )
    types = [e["type"] for e in _bus().published]
    assert types == ["tool.executed", "turn.completed"]
    tool_ev = _bus().published[0]
    assert tool_ev["payload"] == {"name": "get_time", "status": "ok"}
    rows = await _rows(TENANT)
    assert sorted(r.type for r in rows) == ["tool.executed", "turn.completed"]


async def test_denied_tool_emits_denied_status():
    provider = FakeProvider(
        [tool_use_response("quill_finance_summary"), text_response("done")]
    )
    # personal agent's allow-list has no quill tools
    await chat_turn(
        tenant_id=TENANT, agent_id="personal", message="finances?", provider=provider
    )
    tool_ev = next(e for e in _bus().published if e["type"] == "tool.executed")
    assert tool_ev["payload"]["status"] == "denied"


async def test_budget_refusal_emits_budget_exceeded_and_turn_completed():
    provider = FakeProvider([text_response("ok", tin=1000, tout=1000)])
    await chat_turn(
        tenant_id=TENANT, agent_id="personal", message="hello", provider=provider
    )
    async with tenant_session(TENANT) as db:
        await db.execute(
            sa.update(AgentDef)
            .where(AgentDef.tenant_id == TENANT, AgentDef.agent_id == "personal")
            .values(budget_monthly_usd=0.000001)
        )
    provider2 = FakeProvider([text_response("never")])
    result = await chat_turn(
        tenant_id=TENANT, agent_id="personal", message="again", provider=provider2
    )
    assert result.budget_exceeded is True
    types = [e["type"] for e in _bus().published]
    assert types == ["turn.completed", "budget.exceeded", "turn.completed"]
    be = next(e for e in _bus().published if e["type"] == "budget.exceeded")
    # sqlite Numeric(10,2) quantizes the tiny cap — assert the invariant
    assert be["payload"]["month_spend_usd"] >= be["payload"]["budget_monthly_usd"]
    assert be["payload"]["month_spend_usd"] > 0
    last = _bus().published[-1]
    assert last["payload"]["budget_exceeded"] is True
    rows = await _rows(TENANT)
    assert sum(1 for r in rows if r.type == "budget.exceeded") == 1


async def test_inline_bus_dispatches_to_subscribers():
    got = []
    _bus().subscribe(got.append)
    provider = FakeProvider([text_response("hi")])
    await chat_turn(
        tenant_id=TENANT, agent_id="personal", message="hello", provider=provider
    )
    assert len(got) == 1 and got[0]["type"] == "turn.completed"


async def test_publish_failure_never_fails_turn(monkeypatch):
    async def boom(self, event):  # noqa: ARG001
        raise RuntimeError("bus down")

    monkeypatch.setattr(events_mod.InlineBus, "publish", boom)
    provider = FakeProvider([text_response("hi")])
    result = await chat_turn(
        tenant_id=TENANT, agent_id="personal", message="hello", provider=provider
    )
    assert result.reply == "hi"  # turn succeeded despite dead bus
    rows = await _rows(TENANT)  # durable row still committed
    assert [r.type for r in rows] == ["turn.completed"]


class FakePubSubFuture:
    def __init__(self):
        self.resolved = False

    def result(self, timeout=None):  # noqa: ARG002
        self.resolved = True
        return "msg-id-1"


class FakePubSubClient:
    def __init__(self):
        self.calls = []

    def publish(self, topic, data, **attrs):
        self.calls.append((topic, data, attrs))
        return FakePubSubFuture()


async def test_pubsub_bus_publishes_envelope_with_attributes():
    client = FakePubSubClient()
    bus = events_mod.PubSubBus(client_factory=lambda: client)
    ev = events_mod.make_event(
        tenant_id=TENANT,
        agent_id="personal",
        session_id=uuid.uuid4(),
        type="turn.completed",
        payload={"model": "m"},
    )
    await bus.publish(ev)
    assert len(client.calls) == 1
    topic, data, attrs = client.calls[0]
    assert topic.endswith("/topics/agentcloud-events")
    assert json.loads(data.decode()) == ev
    assert attrs["tenant_id"] == TENANT
    assert attrs["type"] == "turn.completed"
    assert attrs["ordering_key"] == ev["session_id"]


async def test_pubsub_bus_selected_by_config(monkeypatch):
    monkeypatch.setattr(events_mod.get_settings(), "EVENT_BUS", "pubsub")
    events_mod.reset_bus()
    assert isinstance(events_mod.get_bus(), events_mod.PubSubBus)
