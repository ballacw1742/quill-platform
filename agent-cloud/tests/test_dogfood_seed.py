"""Tests for the Phase E dogfood seed recipe (scripts/dogfood_seed.py).

Proves: the dry-run plan is pure/writes nothing; a real run provisions the
tenant + both seeds + the dogfood agent and applies the budget override; and
a second run is idempotent (the dogfood agent is reported already-existing,
no duplicate, no error).
"""

from __future__ import annotations

import sqlalchemy as sa

from app.db import tenant_session
from app.models import AgentDef
from scripts.dogfood_seed import build_plan, run

TENANT = "user-charles"


def test_build_plan_is_pure_and_marks_no_go_live():
    plan = build_plan(TENANT, "dogfood", "claude-fable-5", 50.0)
    assert plan["tenant"] == TENANT
    assert plan["activates_go_live"] is False
    # budget step present when a budget is passed
    steps = [s["step"] for s in plan["steps"]]
    assert "set tenant budget override" in steps
    assert "create dogfood agent" in steps
    # the embedded agent goes through the real slug/tools the CRUD expects
    agent = next(s["agent"] for s in plan["steps"] if s["step"] == "create dogfood agent")
    assert agent["agent_id"] == "dogfood"
    assert agent["memory_policy"] == "auto_recall"


def test_build_plan_omits_budget_step_when_none():
    plan = build_plan(TENANT, "dogfood", "claude-fable-5", None)
    steps = [s["step"] for s in plan["steps"]]
    assert "set tenant budget override" not in steps


async def _agent_ids() -> list[str]:
    async with tenant_session(TENANT) as db:
        rows = (
            await db.execute(
                sa.select(AgentDef.agent_id)
                .where(AgentDef.tenant_id == TENANT)
                .order_by(AgentDef.agent_id)
            )
        ).scalars().all()
    return list(rows)


async def _tenant_budget():
    async with tenant_session(TENANT) as db:
        return (
            await db.execute(
                sa.text(
                    "SELECT budget_monthly_usd FROM agentcloud_tenants "
                    "WHERE tenant_id = :t"
                ),
                {"t": TENANT},
            )
        ).scalar_one()


async def test_dry_run_writes_nothing(capsys):
    await run(TENANT, "dogfood", "claude-fable-5", 50.0, dry_run=True)
    # No tenant/agents created by a dry run.
    assert await _agent_ids() == []


async def test_real_run_seeds_and_creates_dogfood_agent():
    await run(TENANT, "dogfood", "claude-fable-5", 50.0, dry_run=False)
    ids = await _agent_ids()
    assert ids == ["dogfood", "personal", "quill"]
    assert float(await _tenant_budget()) == 50.0


async def test_second_run_is_idempotent():
    await run(TENANT, "dogfood", "claude-fable-5", 50.0, dry_run=False)
    await run(TENANT, "dogfood", "claude-fable-5", 50.0, dry_run=False)
    ids = await _agent_ids()
    # exactly one dogfood agent, no duplicate, still all three present
    assert ids == ["dogfood", "personal", "quill"]
