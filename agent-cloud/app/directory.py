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

from app.config import get_settings
from app.db import tenant_session
from app.models import AgentDef, Message, Session, Tenant
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
