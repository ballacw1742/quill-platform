"""Usage/meters API shapes + cross-tenant isolation (LIMITS.md §2)."""

import httpx
import pytest

import app.orchestrator as orch_mod
from app.api import app
from app.db import tenant_session
from app.directory import get_usage
from app.models import Tenant
from app.orchestrator import chat_turn
import sqlalchemy as sa
from tests.conftest import FakeProvider, text_response


@pytest.fixture
def client():
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_usage_fresh_tenant_zero_report():
    """A never-chatted tenant provisions seeds and returns a well-formed
    zero-usage report (every seed agent present, ordered)."""
    report = await get_usage("smoke-usage-fresh")
    assert report["tenant"]["spend_usd"] == 0.0
    assert report["tenant"]["exhausted"] is False
    assert report["tenant"]["budget_source"] == "default"
    agent_ids = [a["agent_id"] for a in report["agents"]]
    assert agent_ids == sorted(agent_ids)
    assert "personal" in agent_ids and "quill" in agent_ids
    for a in report["agents"]:
        assert a["spend_usd"] == 0.0
        assert a["requests"] == 0
        assert a["remaining_usd"] == a["budget_monthly_usd"]


async def test_usage_reflects_spend_and_remaining():
    t = "smoke-usage-spend"
    p = FakeProvider([text_response("ok", tin=1000, tout=1000)])
    await chat_turn(tenant_id=t, agent_id="personal", message="hi", provider=p)
    report = await get_usage(t)
    personal = next(a for a in report["agents"] if a["agent_id"] == "personal")
    assert personal["spend_usd"] > 0
    assert personal["requests"] == 1
    assert personal["input_tokens"] == 1000
    assert personal["output_tokens"] == 1000
    # tenant total >= the one agent's spend
    assert report["tenant"]["spend_usd"] >= personal["spend_usd"]
    assert report["tenant"]["requests"] == 1
    # remaining = budget - spend
    exp = round(personal["budget_monthly_usd"] - personal["spend_usd"], 6)
    assert personal["remaining_usd"] == exp


async def test_usage_month_field_and_override_source():
    t = "smoke-usage-override"
    async with tenant_session(t) as db:
        db.add(Tenant(tenant_id=t, budget_monthly_usd=5.0))
    report = await get_usage(t)
    assert report["tenant"]["budget_source"] == "override"
    assert report["tenant"]["budget_monthly_usd"] == 5.0
    assert len(report["month"]) == 7 and report["month"][4] == "-"


async def test_usage_api_endpoint_shape(client):
    async with client:
        r = await client.get("/v1/agents/usage", params={"tenant_id": "smoke-usage-ep"})
    assert r.status_code == 200
    body = r.json()
    assert "month" in body and "tenant" in body and "agents" in body
    assert "remaining_usd" in body["tenant"]


async def test_usage_is_tenant_scoped_no_cross_leak():
    """Spend on tenant A must not appear in tenant B's report."""
    a, b = "smoke-usage-a", "smoke-usage-b"
    p = FakeProvider([text_response("ok", tin=5000, tout=5000)])
    await chat_turn(tenant_id=a, agent_id="personal", message="hi", provider=p)
    report_b = await get_usage(b)
    assert report_b["tenant"]["spend_usd"] == 0.0
    for agent in report_b["agents"]:
        assert agent["spend_usd"] == 0.0
