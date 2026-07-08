"""Budget metering: per (tenant, agent, day) usage rows + hard monthly caps.

Two caps gate every turn (LIMITS.md §1):
  - the agent cap (agentcloud_agents.budget_monthly_usd — the original A1
    gate), and
  - the tenant cap (B2): agentcloud_tenants.budget_monthly_usd, where NULL
    defers to config (TENANT_BUDGET_DEFAULT_USD for user-* personal
    tenants, ORG_TENANT_BUDGET_USD otherwise).
Exceeding either produces a *polite refusal* on the chat path — never a
silent failure (design doc §6 metering; the $20-cap pattern, platformized).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Tenant, Usage
from app.providers.pricing import cost_usd

log = logging.getLogger("agentcloud.budget")

# user-* personal tenants (TENANCY.md §1) default to the cheaper personal cap.
USER_TENANT_PREFIX = "user-"

BUDGET_REFUSAL_TEMPLATE = (
    "I'm sorry — this agent has reached its monthly usage budget "
    "(${spent:.2f} of ${budget:.2f} for {month}). To keep costs predictable "
    "I can't run any more model calls this month. The budget resets on the "
    "1st, or an administrator can raise this agent's budget_monthly_usd."
)

# Tenant-scope refusal names the *workspace* budget (LIMITS.md §1): the user
# should not hunt for a per-agent setting when the whole workspace is capped.
TENANT_BUDGET_REFUSAL_TEMPLATE = (
    "I'm sorry — this workspace has reached its monthly usage budget "
    "(${spent:.2f} of ${budget:.2f} for {month}, across all of its agents). "
    "To keep costs predictable I can't run any more model calls this month. "
    "The budget resets on the 1st, or an administrator can raise this "
    "workspace's budget_monthly_usd."
)


def month_start(today: date | None = None) -> date:
    d = today or datetime.now(timezone.utc).date()
    return d.replace(day=1)


async def month_spend_usd(
    session: AsyncSession, tenant_id: str, agent_id: str
) -> float:
    """Total metered cost for one agent for the current calendar month (UTC)."""
    q = (
        sa.select(sa.func.coalesce(sa.func.sum(Usage.cost_usd), 0))
        .where(
            Usage.tenant_id == tenant_id,
            Usage.agent_id == agent_id,
            Usage.day >= month_start(),
        )
    )
    return float((await session.execute(q)).scalar_one())


async def tenant_month_spend_usd(session: AsyncSession, tenant_id: str) -> float:
    """Total metered cost across ALL of a tenant's agents this month (UTC).

    This is the truth for the tenant cap: it sums usage rows for agents that
    were deleted mid-month too (LIMITS.md §2), because the rows outlive the
    agent definition.
    """
    q = sa.select(sa.func.coalesce(sa.func.sum(Usage.cost_usd), 0)).where(
        Usage.tenant_id == tenant_id,
        Usage.day >= month_start(),
    )
    return float((await session.execute(q)).scalar_one())


def default_tenant_budget(tenant_id: str) -> float:
    """Config default when agentcloud_tenants.budget_monthly_usd is NULL
    (LIMITS.md §1): user-* personal tenants get the personal cap, everything
    else (org quill-main, smoke-*) gets the org cap."""
    s = get_settings()
    if tenant_id.startswith(USER_TENANT_PREFIX):
        return float(s.TENANT_BUDGET_DEFAULT_USD)
    return float(s.ORG_TENANT_BUDGET_USD)


async def resolve_tenant_budget(
    session: AsyncSession, tenant_id: str
) -> tuple[float, str]:
    """Return (effective_budget_usd, source) for a tenant.

    source is "override" when agentcloud_tenants.budget_monthly_usd is a
    non-NULL explicit value, else "default" (config-derived). LIMITS.md §2
    exposes `budget_source` on the usage API from this.
    """
    override = (
        await session.execute(
            sa.select(Tenant.budget_monthly_usd).where(
                Tenant.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if override is not None:
        return float(override), "override"
    return default_tenant_budget(tenant_id), "default"


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


def refusal_message(spent: float, budget: float, scope: str = "agent") -> str:
    """Polite refusal text. scope="agent" names the agent budget; scope=
    "tenant" names the workspace budget (LIMITS.md §1 precedence: agent wins
    when both are exhausted)."""
    template = (
        TENANT_BUDGET_REFUSAL_TEMPLATE
        if scope == "tenant"
        else BUDGET_REFUSAL_TEMPLATE
    )
    return template.format(
        spent=spent, budget=budget, month=datetime.now(timezone.utc).strftime("%B %Y")
    )
