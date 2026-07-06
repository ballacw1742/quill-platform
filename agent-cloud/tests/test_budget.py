import sqlalchemy as sa

from app import budget
from app.db import tenant_session
from app.models import AgentDef, Usage
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
