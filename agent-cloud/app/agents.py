"""Agent-definition CRUD, validation, tool-palette catalog, and templates.

Phase C "Agent Builder" (design doc §3.3; contract: agent-cloud/AGENT_BUILDER.md).
An agent is one `agentcloud_agents` row; this module is the create/patch/
soft-delete surface over it plus the static catalog + templates that back the
web builder form.

Discipline (identical to directory.py): every query filters `tenant_id` at the
app layer AND runs inside `tenant_session()` so RLS is the second belt.
Cross-tenant ids are 404 (no existence oracle, TENANCY.md §4).
"""

from __future__ import annotations

import re
from typing import Any

import sqlalchemy as sa

from app import budget as budget_mod
from app import events as events_mod
from app.config import get_settings
from app.db import tenant_session
from app.directory import _provision_tenant
from app.models import AgentDef
from app.providers.pricing import DEFAULT_PRICING
from app.seeds import SEED_AGENTS, seed_model_for_tenant
from app.tools import REGISTRY
from app.tools.builtin import BUILTIN_TOOLS
from app.tools.memory import MEMORY_TOOL_NAMES, MEMORY_TOOLS
from app.tools.quill import QUILL_TOOLS
from app.tools.quill_writes import (
    EMAIL_WRITE_TOOL_NAMES,
    EMAIL_WRITE_TOOLS,
    QUILL_WRITE_TOOL_NAMES,
    QUILL_WRITE_TOOLS,
)
from app.tools.web_tools import WEB_TOOL_NAMES, WEB_TOOLS

# --- constants / catalog -----------------------------------------------------

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
MEMORY_POLICIES = ("off", "tools_only", "auto_recall")
SEED_AGENT_IDS = frozenset(s.agent_id for s in SEED_AGENTS)

# Allowed model aliases = keys of the pricing table (source of truth,
# app/providers/pricing.py). A versioned `@date` suffix is tolerated exactly
# like pricing._lookup does.
ALLOWED_MODELS = tuple(DEFAULT_PRICING.keys())

# Short human labels for the palette (falls back to the tool name if absent,
# so a newly-registered tool never breaks the catalog).
TOOL_LABELS: dict[str, str] = {
    "get_time": "Current time",
    "quill_finance_summary": "Finance summary",
    "quill_pipeline_summary": "Sales pipeline summary",
    "quill_operations_summary": "Operations summary",
    "quill_customers_summary": "Customers summary",
    "quill_intelligence_brief": "Intelligence brief",
    "quill_list_pending_approvals": "List pending approvals",
    "memory_save": "Save memory",
    "memory_search": "Search memory",
    "quill_project_update": "Update project",
    "quill_project_log_note": "Add project log note",
    "quill_project_milestone_create": "Create project milestone",
    "quill_deal_update": "Update deal",
    "quill_request_update": "Update request",
    # §9 Wave 2 additions
    "quill_email_send": "Send email (approval-gated)",
    "quill_web_fetch": "Web fetch (read-only)",
}

# All approval-gated write tool names (used for the approval_gated flag in
# the catalog; kept as a set for O(1) lookup).
_ALL_WRITE_TOOL_NAMES: frozenset[str] = frozenset(
    QUILL_WRITE_TOOL_NAMES + EMAIL_WRITE_TOOL_NAMES
)

_GROUPS = (
    ("builtin", "Built-in", [t.name for t in BUILTIN_TOOLS]),
    ("read", "Quill (read-only)", [t.name for t in QUILL_TOOLS]),
    ("memory", "Memory", [t.name for t in MEMORY_TOOLS]),
    ("write", "Quill writes (approval-gated)", [t.name for t in QUILL_WRITE_TOOLS]),
    # §9 Wave 2 additions
    ("email", "Email (approval-gated)", [t.name for t in EMAIL_WRITE_TOOLS]),
    ("web", "Web (read-only)", [t.name for t in WEB_TOOLS]),
)


class AgentValidationError(ValueError):
    """400 — a field failed a validation rule (AGENT_BUILDER.md §4)."""


class AgentNotFoundError(LookupError):
    """404 — unknown or cross-tenant agent id."""


class AgentConflictError(ValueError):
    """409 — agent_id already exists for this tenant."""


class SeedProtectedError(PermissionError):
    """403 — a destructive op on a seed agent (AGENT_BUILDER.md §3)."""


# --- catalog / templates (static) --------------------------------------------


def tool_catalog() -> dict[str, Any]:
    """AGENT_BUILDER.md §5 — palette grouped from the registry (source of
    truth); labels/approval-gated flags layered on top."""
    groups = []
    for group_id, label, names in _GROUPS:
        tools = []
        for name in names:
            tool = REGISTRY.get(name)
            if tool is None:  # pragma: no cover — registry drift guard
                continue
            tools.append(
                {
                    "name": name,
                    "label": TOOL_LABELS.get(name, name),
                    "description": tool.description,
                    "approval_gated": name in _ALL_WRITE_TOOL_NAMES,
                    "memory_tool": name in MEMORY_TOOL_NAMES,
                }
            )
        groups.append({"group": group_id, "label": label, "tools": tools})
    return {
        "groups": groups,
        "models": list(ALLOWED_MODELS),
        "memory_policies": list(MEMORY_POLICIES),
    }


_READ_TOOLS = [t.name for t in BUILTIN_TOOLS] + [t.name for t in QUILL_TOOLS]


def templates() -> dict[str, Any]:
    """AGENT_BUILDER.md §6 — 3 static clone-to-create starters."""
    return {
        "templates": [
            {
                "template_id": "research-assistant",
                "name": "Research Assistant",
                "summary": "Read-only Quill portfolio Q&A. No writes, no memory.",
                "system_prompt": (
                    "You are a research assistant for the Quill portfolio. "
                    "Answer questions using your read-only tools (finance, "
                    "pipeline, operations, customers, the intelligence brief, "
                    "and the pending-approvals queue). Cite concrete numbers "
                    "from tool results. You cannot write or change anything."
                ),
                "model": get_settings().MODEL_DEFAULT,
                "tools": list(_READ_TOOLS),
                "memory_policy": "off",
                "budget_monthly_usd": 10.0,
            },
            {
                "template_id": "ops-analyst",
                "name": "Ops Analyst",
                "summary": (
                    "Read-only Quill analysis with memory — remembers summaries "
                    "and findings across sessions. Still no writes."
                ),
                "system_prompt": (
                    "You are an operations analyst for the Quill portfolio. Use "
                    "your read-only tools to analyze the business, and save "
                    "durable summaries and findings with memory_save so you can "
                    "build on them across sessions (memory_search to recall). "
                    "You cannot write or change anything in Quill."
                ),
                "model": get_settings().MODEL_DEFAULT,
                "tools": list(_READ_TOOLS) + ["memory_save", "memory_search"],
                "memory_policy": "tools_only",
                "budget_monthly_usd": 10.0,
            },
            {
                "template_id": "project-copilot",
                "name": "Project Copilot",
                "summary": (
                    "Full project copilot: reads Quill, remembers context, and "
                    "can PROPOSE project writes — every write is queued for human "
                    "approval in the Quill queue."
                ),
                "system_prompt": (
                    "You are a project copilot for the Quill portfolio. Use your "
                    "read-only tools to understand the business, remember context "
                    "with memory, and PROPOSE project updates, log notes, and "
                    "milestones when helpful. Writes never happen immediately — "
                    "each is queued for human approval in the Quill queue, and "
                    "you are woken when it is approved, declined, or expires."
                ),
                "model": get_settings().MODEL_DEFAULT,
                "tools": (
                    list(_READ_TOOLS)
                    + ["memory_save", "memory_search"]
                    + [
                        "quill_project_update",
                        "quill_project_log_note",
                        "quill_project_milestone_create",
                    ]
                ),
                "memory_policy": "auto_recall",
                "budget_monthly_usd": 10.0,
            },
        ]
    }


# --- serialization -----------------------------------------------------------


def _detail_dict(a: AgentDef) -> dict[str, Any]:
    """AGENT_BUILDER.md §1 — the detail shape (superset of the A5 list dict)."""
    return {
        "agent_id": a.agent_id,
        "system_prompt": a.system_prompt,
        "model": a.model,
        "tools": list(a.tools or []),
        "memory_policy": a.memory_policy,
        "budget_monthly_usd": float(a.budget_monthly_usd),
        "enabled": a.enabled,
        "is_seed": a.agent_id in SEED_AGENT_IDS,
        "created_at": a.created_at,
    }


# --- validation helpers ------------------------------------------------------


def _validate_slug(agent_id: str) -> str:
    agent_id = (agent_id or "").strip()
    if not SLUG_RE.match(agent_id):
        raise AgentValidationError(
            "agent_id must be a slug: lowercase letters/digits and internal "
            "hyphens, 1-63 chars, no leading/trailing hyphen"
        )
    return agent_id


def _validate_prompt(system_prompt: str) -> str:
    text = (system_prompt or "").strip()
    if not text:
        raise AgentValidationError("system_prompt must not be empty")
    cap = get_settings().SYSTEM_PROMPT_MAX_CHARS
    if len(text) > cap:
        raise AgentValidationError(
            f"system_prompt exceeds the {cap}-character limit"
        )
    return text


def _validate_tools(tools: list[str]) -> list[str]:
    if tools is None:
        return []
    if not isinstance(tools, list):
        raise AgentValidationError("tools must be a list of tool names")
    out: list[str] = []
    seen: set[str] = set()
    for name in tools:
        if not isinstance(name, str):
            raise AgentValidationError("tools must be a list of tool names")
        if name not in REGISTRY:
            raise AgentValidationError(f"unknown tool {name!r}")
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _validate_model(model: str) -> str:
    model = (model or "").strip()
    base = model.split("@", 1)[0]
    if base not in ALLOWED_MODELS:
        raise AgentValidationError(
            f"model {model!r} is not allowed; choose one of "
            f"{', '.join(ALLOWED_MODELS)}"
        )
    return model


def _validate_memory_policy(policy: str) -> str:
    if policy not in MEMORY_POLICIES:
        raise AgentValidationError(
            f"memory_policy must be one of {', '.join(MEMORY_POLICIES)}"
        )
    return policy


async def _validate_budget(db, tenant_id: str, budget: float) -> float:
    try:
        value = float(budget)
    except (TypeError, ValueError) as exc:
        raise AgentValidationError("budget_monthly_usd must be a number") from exc
    if value <= 0:
        raise AgentValidationError("budget_monthly_usd must be greater than 0")
    tenant_cap, _source = await budget_mod.resolve_tenant_budget(db, tenant_id)
    if value > tenant_cap:
        raise AgentValidationError(
            f"budget_monthly_usd ({value:g}) exceeds the tenant monthly cap "
            f"({tenant_cap:g})"
        )
    return value


def _emit_agent_updated(db, tenant_id: str, agent_id: str, action: str, fields: list[str]):
    ev = events_mod.make_event(
        tenant_id=tenant_id,
        agent_id=agent_id,
        type="agent.updated",
        payload={"action": action, "fields": fields},
    )
    events_mod.record_events(db, [ev])
    return ev


# --- CRUD --------------------------------------------------------------------


async def get_agent(tenant_id: str, agent_id: str) -> dict:
    """AGENT_BUILDER.md §2 — detail read; 404 unknown/cross-tenant."""
    async with tenant_session(tenant_id) as db:
        await _provision_tenant(db, tenant_id)
        row = await _load(db, tenant_id, agent_id)
        return _detail_dict(row)


async def _load(db, tenant_id: str, agent_id: str) -> AgentDef:
    row = (
        await db.execute(
            sa.select(AgentDef).where(
                AgentDef.tenant_id == tenant_id,
                AgentDef.agent_id == agent_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise AgentNotFoundError("agent not found for this tenant")
    return row


async def create_agent(tenant_id: str, data: dict) -> dict:
    """AGENT_BUILDER.md §2.1 — create; 400 validation, 409 duplicate."""
    s = get_settings()
    async with tenant_session(tenant_id) as db:
        await _provision_tenant(db, tenant_id)

        agent_id = _validate_slug(str(data.get("agent_id", "")))
        # duplicate (incl. reserved seed ids, which already exist) → 409
        existing = (
            await db.execute(
                sa.select(AgentDef.agent_id).where(
                    AgentDef.tenant_id == tenant_id,
                    AgentDef.agent_id == agent_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise AgentConflictError(
                f"agent_id {agent_id!r} already exists for this tenant"
            )

        system_prompt = _validate_prompt(str(data.get("system_prompt", "")))
        model = _validate_model(
            str(data.get("model") or seed_model_for_tenant(tenant_id))
        )
        tools = _validate_tools(data.get("tools", []) or [])
        memory_policy = _validate_memory_policy(str(data.get("memory_policy", "off")))
        budget = await _validate_budget(
            db,
            tenant_id,
            data.get("budget_monthly_usd", s.DEFAULT_BUDGET_MONTHLY_USD),
        )
        enabled = bool(data.get("enabled", True))

        row = AgentDef(
            tenant_id=tenant_id,
            agent_id=agent_id,
            system_prompt=system_prompt,
            model=model,
            tools=tools,
            budget_monthly_usd=budget,
            enabled=enabled,
            memory_policy=memory_policy,
        )
        db.add(row)
        ev = _emit_agent_updated(db, tenant_id, agent_id, "created", ["*"])
        await db.flush()
        await db.refresh(row)
        detail = _detail_dict(row)
    await events_mod.emit([ev])
    return detail


async def update_agent(tenant_id: str, agent_id: str, patch: dict) -> dict:
    """AGENT_BUILDER.md §2.2 — partial update; seed-protected fields → 403."""
    is_seed = agent_id in SEED_AGENT_IDS
    async with tenant_session(tenant_id) as db:
        await _provision_tenant(db, tenant_id)
        row = await _load(db, tenant_id, agent_id)

        changed: list[str] = []
        if "system_prompt" in patch:
            row.system_prompt = _validate_prompt(str(patch["system_prompt"]))
            changed.append("system_prompt")
        if "model" in patch:
            row.model = _validate_model(str(patch["model"]))
            changed.append("model")
        if "tools" in patch:
            row.tools = _validate_tools(patch["tools"])
            changed.append("tools")
        if "memory_policy" in patch:
            row.memory_policy = _validate_memory_policy(str(patch["memory_policy"]))
            changed.append("memory_policy")
        if "budget_monthly_usd" in patch:
            row.budget_monthly_usd = await _validate_budget(
                db, tenant_id, patch["budget_monthly_usd"]
            )
            changed.append("budget_monthly_usd")
        if "enabled" in patch:
            enabled = bool(patch["enabled"])
            # Disabling a seed would break the assistant picker (§3).
            if is_seed and not enabled:
                raise SeedProtectedError(
                    f"seed agent {agent_id!r} cannot be disabled"
                )
            row.enabled = enabled
            changed.append("enabled")

        if not changed:
            return _detail_dict(row)

        ev = _emit_agent_updated(db, tenant_id, agent_id, "updated", changed)
        await db.flush()
        await db.refresh(row)
        detail = _detail_dict(row)
    await events_mod.emit([ev])
    return detail


async def delete_agent(tenant_id: str, agent_id: str) -> dict:
    """AGENT_BUILDER.md §2 — SOFT delete (enabled=false). Seeds → 403.
    History (sessions/memory/usage/…) is never hard-deleted."""
    if agent_id in SEED_AGENT_IDS:
        raise SeedProtectedError(f"seed agent {agent_id!r} cannot be deleted")
    async with tenant_session(tenant_id) as db:
        await _provision_tenant(db, tenant_id)
        row = await _load(db, tenant_id, agent_id)
        row.enabled = False
        ev = _emit_agent_updated(db, tenant_id, agent_id, "deleted", ["enabled"])
        await db.flush()
    await events_mod.emit([ev])
    return {"agent_id": agent_id, "enabled": False, "soft_deleted": True}
