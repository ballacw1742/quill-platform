import sqlalchemy as sa

from app import budget
from app import events as events_mod
from app.db import tenant_session
from app.models import AgentDef, Tenant, Usage
from app.orchestrator import chat_turn
from tests.conftest import FakeProvider, text_response

TENANT = "smoke-tenant-budget"


async def test_record_usage_upserts_and_sums():
    async with tenant_session(TENANT) as db:
        c1 = await budget.record_usage(
            db, tenant_id=TENANT, agent_id="personal", model="claude-haiku-4-5",
            input_tokens=1000, output_tokens=2000,
        )
        c2 = await budget.record_usage(
            db, tenant_id=TENANT, agent_id="personal", model="claude-haiku-4-5",
            input_tokens=500, output_tokens=500,
        )
    async with tenant_session(TENANT) as db:
        row = (
            await db.execute(
                sa.select(Usage).where(Usage.tenant_id == TENANT)
            )
        ).scalar_one()
        assert row.input_tokens == 1500
        assert row.output_tokens == 2500
        assert row.requests == 2
        assert float(row.cost_usd) > 0
        spend = await budget.month_spend_usd(db, TENANT, "personal")
        assert abs(spend - (c1 + c2)) < 1e-9


async def test_turn_records_usage():
    provider = FakeProvider([text_response("hi there", tin=100, tout=50)])
    result = await chat_turn(
        tenant_id=TENANT, agent_id="personal", message="hello", provider=provider
    )
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    assert result.cost_usd > 0
    async with tenant_session(TENANT) as db:
        spend = await budget.month_spend_usd(db, TENANT, "personal")
        assert spend > 0


async def test_budget_cap_triggers_polite_refusal_not_silent_failure():
    # Turn 1 seeds the tenant + burns some budget.
    provider = FakeProvider([text_response("ok", tin=1000, tout=1000)])
    await chat_turn(
        tenant_id=TENANT, agent_id="personal", message="hello", provider=provider
    )
    # Drop the cap below what was just spent.
    async with tenant_session(TENANT) as db:
        await db.execute(
            sa.update(AgentDef)
            .where(AgentDef.tenant_id == TENANT, AgentDef.agent_id == "personal")
            .values(budget_monthly_usd=0.000001)
        )
    # Turn 2 must refuse politely — and never call the model.
    provider2 = FakeProvider([text_response("should never be used")])
    result = await chat_turn(
        tenant_id=TENANT, agent_id="personal", message="hello again", provider=provider2
    )
    assert result.budget_exceeded is True
    assert "budget" in result.reply.lower()
    assert provider2.calls == 0
    # Refusal is persisted in history (not silent).
    provider3 = FakeProvider([text_response("x")])
    result2 = await chat_turn(
        tenant_id=TENANT, agent_id="personal", message="still there?",
        session_id=result.session_id, provider=provider3,
    )
    assert result2.budget_exceeded is True


async def test_budget_is_per_agent():
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
    # The quill agent has its own budget — unaffected.
    provider2 = FakeProvider([text_response("quill fine")])
    result = await chat_turn(
        tenant_id=TENANT, agent_id="quill", message="hello", provider=provider2
    )
    assert result.budget_exceeded is False
    assert result.reply == "quill fine"


# --- B2: tenant-level budget (LIMITS.md §1) -----------------------------


async def test_default_tenant_budget_user_vs_org(monkeypatch):
    monkeypatch.setenv("TENANT_BUDGET_DEFAULT_USD", "10")
    monkeypatch.setenv("ORG_TENANT_BUDGET_USD", "100")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        assert budget.default_tenant_budget("user-42") == 10.0
        assert budget.default_tenant_budget("quill-main") == 100.0
        assert budget.default_tenant_budget("smoke-x") == 100.0
    finally:
        get_settings.cache_clear()


async def test_resolve_tenant_budget_override_vs_default():
    t = "user-resolve"
    async with tenant_session(t) as db:
        db.add(Tenant(tenant_id=t))
    async with tenant_session(t) as db:
        budget_usd, source = await budget.resolve_tenant_budget(db, t)
        assert source == "default"
    async with tenant_session(t) as db:
        await db.execute(
            sa.update(Tenant).where(Tenant.tenant_id == t).values(budget_monthly_usd=3.5)
        )
    async with tenant_session(t) as db:
        budget_usd, source = await budget.resolve_tenant_budget(db, t)
        assert source == "override"
        assert abs(budget_usd - 3.5) < 1e-9


async def test_tenant_cap_refuses_even_when_agent_has_room(monkeypatch):
    # Set a tiny tenant budget so the tenant total trips while the per-agent
    # cap ($20) still has room — proves the tenant gate is independent.
    t = "smoke-tenant-cap"
    monkeypatch.setenv("ORG_TENANT_BUDGET_USD", "100")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        # burn some tenant spend on `personal`
        p1 = FakeProvider([text_response("ok", tin=1000, tout=1000)])
        await chat_turn(tenant_id=t, agent_id="personal", message="hi", provider=p1)
        # override tenant budget below the current tenant total
        async with tenant_session(t) as db:
            await db.execute(
                sa.update(Tenant)
                .where(Tenant.tenant_id == t)
                .values(budget_monthly_usd=0.000001)
            )
        # a DIFFERENT agent (its own $20 cap untouched) must still be refused,
        # and the refusal names the WORKSPACE budget.
        p2 = FakeProvider([text_response("should never run")])
        result = await chat_turn(
            tenant_id=t, agent_id="quill", message="hi", provider=p2
        )
        assert result.budget_exceeded is True
        assert p2.calls == 0
        assert "workspace" in result.reply.lower()
    finally:
        get_settings.cache_clear()


async def test_agent_cap_wins_when_both_exhausted():
    # Both caps exhausted → precedence names the AGENT (LIMITS.md §1).
    t = "smoke-tenant-both"
    p1 = FakeProvider([text_response("ok", tin=1000, tout=1000)])
    await chat_turn(tenant_id=t, agent_id="personal", message="hi", provider=p1)
    async with tenant_session(t) as db:
        await db.execute(
            sa.update(AgentDef)
            .where(AgentDef.tenant_id == t, AgentDef.agent_id == "personal")
            .values(budget_monthly_usd=0.000001)
        )
        await db.execute(
            sa.update(Tenant)
            .where(Tenant.tenant_id == t)
            .values(budget_monthly_usd=0.000001)
        )
    p2 = FakeProvider([text_response("nope")])
    result = await chat_turn(
        tenant_id=t, agent_id="personal", message="hi", provider=p2
    )
    assert result.budget_exceeded is True
    # scope=agent → refusal names the agent budget, not the workspace
    assert "this agent" in result.reply.lower()
    # budget.exceeded event carries scope + both pairs
    bus = events_mod.get_bus()
    exceeded = [e for e in bus.published if e["type"] == "budget.exceeded"]
    assert exceeded, "expected a budget.exceeded event"
    payload = exceeded[-1]["payload"]
    assert payload["scope"] == "agent"
    assert "tenant_budget_monthly_usd" in payload
    assert "budget_monthly_usd" in payload
