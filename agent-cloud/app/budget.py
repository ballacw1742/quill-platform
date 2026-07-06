"""Budget metering: per (tenant, agent, day) usage rows + hard monthly cap.

The cap comes from the agent definition (budget_monthly_usd). Exceeding it
produces a *polite refusal* on the chat path — never a silent failure
(design doc §6 metering; the $20-cap pattern, platformized).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Usage
from app.providers.pricing import cost_usd

log = logging.getLogger("agentcloud.budget")

BUDGET_REFUSAL_TEMPLATE = (
    "I'm sorry — this agent has reached its monthly usage budget "
    "(${spent:.2f} of ${budget:.2f} for {month}). To keep costs predictable "
    "I can't run any more model calls this month. The budget resets on the "
    "1st, or an administrator can raise this agent's budget_monthly_usd."
)


def month_start(today: date | None = None) -> date:
    d = today or datetime.now(timezone.utc).date()
    return d.replace(day=1)


async def month_spend_usd(
    session: AsyncSession, tenant_id: str, agent_id: str
) -> float:
    """Total metered cost for the current calendar month (UTC)."""
    q = (
        sa.select(sa.func.coalesce(sa.func.sum(Usage.cost_usd), 0))
        .where(
            Usage.tenant_id == tenant_id,
            Usage.agent_id == agent_id,
            Usage.day >= month_start(),
        )
    )
    return float((await session.execute(q)).scalar_one())


async def record_usage(
    session: AsyncSession,
    *,
    tenant_id: str,
    agent_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    calls: int = 1,
) -> float:
    """Upsert today's usage row; returns the cost of this increment."""
    cost = cost_usd(model, input_tokens, output_tokens)
    today = datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc)

    dialect = session.bind.dialect.name if session.bind is not None else "sqlite"
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(Usage)
    else:
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = sqlite_insert(Usage)

    stmt = stmt.values(
        tenant_id=tenant_id,
        agent_id=agent_id,
        day=today,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        requests=calls,
        updated_at=now,
    ).on_conflict_do_update(
        index_elements=["tenant_id", "agent_id", "day"],
        set_={
            "input_tokens": Usage.input_tokens + input_tokens,
            "output_tokens": Usage.output_tokens + output_tokens,
            "cost_usd": Usage.cost_usd + cost,
            "requests": Usage.requests + calls,
            "updated_at": now,
        },
    )
    await session.execute(stmt)
    log.info(
        "usage recorded",
        extra={
            "extra_fields": {
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": round(cost, 6),
            }
        },
    )
    return cost


def refusal_message(spent: float, budget: float) -> str:
    return BUDGET_REFUSAL_TEMPLATE.format(
        spent=spent, budget=budget, month=datetime.now(timezone.utc).strftime("%B %Y")
    )
