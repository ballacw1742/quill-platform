"""Tenant-scoped read endpoints' query layer (A5 web-chat channel).

WEBCHAT.md §5 is the contract for these shapes. Three reads back the Quill
web bridge: agents list (with idempotent tenant provisioning so a fresh
tenant sees its seed agents before ever chatting), sessions list (newest
first, with a first-user-message preview), and a full session transcript.

Same discipline as every other request path: every query filters tenant_id
at the app layer AND runs inside tenant_session() so RLS is the second belt.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa

from app import budget as budget_mod
from app.config import get_settings
from app.db import tenant_session
from app.models import AgentDef, Message, Session, Tenant, Usage
from app.orchestrator import _insert_ignore
from app.seeds import SEED_AGENTS, seed_model_for_tenant

PREVIEW_MAX_CHARS = 120


class DirectorySessionNotFoundError(LookupError):
    pass


async def _provision_tenant(db, tenant_id: str) -> None:
    """Idempotent tenant + seed-agent provisioning (same path as _prepare)."""
    s = get_settings()
    dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
    await db.execute(_insert_ignore(Tenant, {"tenant_id": tenant_id}, dialect))
    seed_model = seed_model_for_tenant(tenant_id)
    for seed in SEED_AGENTS:
        await db.execute(
            _insert_ignore(
                AgentDef,
                {
                    "tenant_id": tenant_id,
                    "agent_id": seed.agent_id,
                    "system_prompt": seed.system_prompt.format(tenant_id=tenant_id),
                    "model": seed_model,
                    "tools": list(seed.tools),
                    "budget_monthly_usd": s.DEFAULT_BUDGET_MONTHLY_USD,
                    "enabled": True,
                    "memory_policy": seed.memory_policy,
                    "model_lane": seed.model_lane,
                },
                dialect,
            )
        )


def _agent_dict(a: AgentDef) -> dict[str, Any]:
    return {
        "agent_id": a.agent_id,
        "model": a.model,
        "enabled": a.enabled,
        "memory_policy": a.memory_policy,
        "model_lane": getattr(a, "model_lane", "local") or "local",
        "budget_monthly_usd": float(a.budget_monthly_usd),
        "created_at": a.created_at,
    }


async def list_agents(tenant_id: str, *, limit: int = 100, offset: int = 0) -> dict:
    """WEBCHAT.md §3.1 — provision (idempotent) then list the tenant's agents."""
    async with tenant_session(tenant_id) as db:
        await _provision_tenant(db, tenant_id)
        total = (
            await db.execute(
                sa.select(sa.func.count())
                .select_from(AgentDef)
                .where(AgentDef.tenant_id == tenant_id)
            )
        ).scalar_one()
        rows = (
            (
                await db.execute(
                    sa.select(AgentDef)
                    .where(AgentDef.tenant_id == tenant_id)
                    .order_by(AgentDef.agent_id)
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return {
            "items": [_agent_dict(a) for a in rows],
            "total": int(total),
            "limit": limit,
            "offset": offset,
        }


def _preview_from_content(content: Any) -> str | None:
    """First displayable user text: plain string, or first text block that is
    neither a tool_result nor a [system wake] marker."""
    if isinstance(content, str):
        return content[:PREVIEW_MAX_CHARS]
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = str(block.get("text") or "")
                if text.startswith("[system wake]"):
                    return None
                return text[:PREVIEW_MAX_CHARS]
    return None


async def list_sessions(
    tenant_id: str,
    *,
    agent_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """WEBCHAT.md §3.2 — sessions newest-updated first, with preview."""
    async with tenant_session(tenant_id) as db:
        where = [Session.tenant_id == tenant_id]
        if agent_id:
            where.append(Session.agent_id == agent_id)
        total = (
            await db.execute(
                sa.select(sa.func.count()).select_from(Session).where(*where)
            )
        ).scalar_one()
        rows = (
            (
                await db.execute(
                    sa.select(Session)
                    .where(*where)
                    .order_by(Session.updated_at.desc(), Session.session_id)
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )

        previews: dict[uuid.UUID, str] = {}
        if rows:
            sids = [r.session_id for r in rows]
            msgs = (
                await db.execute(
                    sa.select(Message.session_id, Message.content)
                    .where(
                        Message.tenant_id == tenant_id,
                        Message.session_id.in_(sids),
                        Message.role == "user",
                    )
                    .order_by(Message.message_id)
                )
            ).all()
            for m in msgs:
                if m.session_id in previews:
                    continue
                p = _preview_from_content(m.content)
                if p:
                    previews[m.session_id] = p

        return {
            "items": [
                {
                    "session_id": str(r.session_id),
                    "agent_id": r.agent_id,
                    "preview": previews.get(r.session_id, ""),
                    "created_at": r.created_at,
                    "updated_at": r.updated_at,
                }
                for r in rows
            ],
            "total": int(total),
            "limit": limit,
            "offset": offset,
        }


def _round6(x: float) -> float:
    return round(float(x), 6)


async def get_usage(tenant_id: str) -> dict:
    """LIMITS.md §2 — current-month usage/meters for a tenant.

    Idempotently provisions the tenant + seed agents (same path as
    list_agents) so a fresh tenant gets a well-formed zero-usage report,
    then returns per-agent meters (every defined agent, ordered by
    agent_id, zero-usage agents included) plus tenant totals + remaining.
    Deleted-agent usage still counts toward the tenant totals.
    """
    month = budget_mod.month_start().strftime("%Y-%m")
    since = budget_mod.month_start()
    async with tenant_session(tenant_id) as db:
        await _provision_tenant(db, tenant_id)

        # per-agent usage aggregate for the month (may include deleted agents)
        usage_rows = (
            await db.execute(
                sa.select(
                    Usage.agent_id,
                    sa.func.coalesce(sa.func.sum(Usage.input_tokens), 0),
                    sa.func.coalesce(sa.func.sum(Usage.output_tokens), 0),
                    sa.func.coalesce(sa.func.sum(Usage.cost_usd), 0),
                    sa.func.coalesce(sa.func.sum(Usage.requests), 0),
                )
                .where(Usage.tenant_id == tenant_id, Usage.day >= since)
                .group_by(Usage.agent_id)
            )
        ).all()
        usage_by_agent = {
            r[0]: {
                "input_tokens": int(r[1]),
                "output_tokens": int(r[2]),
                "cost_usd": float(r[3]),
                "requests": int(r[4]),
            }
            for r in usage_rows
        }

        # every currently-defined agent (ordered), zero-usage included
        agent_defs = (
            (
                await db.execute(
                    sa.select(AgentDef)
                    .where(AgentDef.tenant_id == tenant_id)
                    .order_by(AgentDef.agent_id)
                )
            )
            .scalars()
            .all()
        )

        tenant_budget, budget_source = await budget_mod.resolve_tenant_budget(
            db, tenant_id
        )
        tenant_spend = await budget_mod.tenant_month_spend_usd(db, tenant_id)

    agents_out = []
    for a in agent_defs:
        u = usage_by_agent.get(
            a.agent_id,
            {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "requests": 0},
        )
        agent_budget = float(a.budget_monthly_usd)
        spend = u["cost_usd"]
        agents_out.append(
            {
                "agent_id": a.agent_id,
                "budget_monthly_usd": _round6(agent_budget),
                "spend_usd": _round6(spend),
                "remaining_usd": _round6(max(0.0, agent_budget - spend)),
                "input_tokens": u["input_tokens"],
                "output_tokens": u["output_tokens"],
                "requests": u["requests"],
                "exhausted": spend >= agent_budget,
            }
        )

    tenant_in = sum(u["input_tokens"] for u in usage_by_agent.values())
    tenant_out = sum(u["output_tokens"] for u in usage_by_agent.values())
    tenant_reqs = sum(u["requests"] for u in usage_by_agent.values())
    return {
        "month": month,
        "tenant": {
            "budget_monthly_usd": _round6(tenant_budget),
            "budget_source": budget_source,
            "spend_usd": _round6(tenant_spend),
            "remaining_usd": _round6(max(0.0, tenant_budget - tenant_spend)),
            "input_tokens": tenant_in,
            "output_tokens": tenant_out,
            "requests": tenant_reqs,
            "exhausted": tenant_spend >= tenant_budget,
        },
        "agents": agents_out,
    }


async def get_transcript(tenant_id: str, session_id: uuid.UUID) -> dict:
    """WEBCHAT.md §3.3 — full transcript; 404 on unknown/cross-tenant."""
    async with tenant_session(tenant_id) as db:
        sess = (
            await db.execute(
                sa.select(Session).where(
                    Session.session_id == session_id,
                    Session.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if sess is None:
            raise DirectorySessionNotFoundError(
                "session not found for this tenant"
            )
        msgs = (
            await db.execute(
                sa.select(Message)
                .where(
                    Message.tenant_id == tenant_id,
                    Message.session_id == session_id,
                )
                .order_by(Message.message_id)
            )
        ).scalars().all()
        return {
            "session_id": str(sess.session_id),
            "agent_id": sess.agent_id,
            "created_at": sess.created_at,
            "updated_at": sess.updated_at,
            "messages": [
                {"role": m.role, "content": m.content, "created_at": m.created_at}
                for m in msgs
            ],
        }
