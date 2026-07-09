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

import logging
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

log = logging.getLogger("agentcloud.agents")

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
MEMORY_POLICIES = ("off", "tools_only", "auto_recall")
SEED_AGENT_IDS = frozenset(s.agent_id for s in SEED_AGENTS)

# ADK_AGENTS_DESIGN.md §1 vocabularies.
AGENT_KINDS = ("assistant", "adk_task")
RUNTIMES = ("claude", "adk")
VISIBILITIES = ("private", "shared")
APPROVAL_STATES = ("draft", "suggested", "approved", "rejected")

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
    """AGENT_BUILDER.md §1 — the detail shape (superset of the A5 list dict).

    Additive ADK fields (ADK_AGENTS_DESIGN.md §1) appended so the builder UI
    can render agent-kind/runtime/visibility/approval_state + adk_config.
    Existing consumers keep working (they read a subset)."""
    return {
        "agent_id": a.agent_id,
        "system_prompt": a.system_prompt,
        "model": a.model,
        "tools": list(a.tools or []),
        "memory_policy": a.memory_policy,
        "budget_monthly_usd": float(a.budget_monthly_usd),
        "enabled": a.enabled,
        "is_seed": a.agent_id in SEED_AGENT_IDS,
        "agent_kind": getattr(a, "agent_kind", "assistant") or "assistant",
        "runtime": getattr(a, "runtime", "claude") or "claude",
        "owner_user_id": getattr(a, "owner_user_id", None),
        "visibility": getattr(a, "visibility", "private") or "private",
        "approval_state": getattr(a, "approval_state", "draft") or "draft",
        "adk_config": getattr(a, "adk_config", None),
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


def _validate_tools(tools: list[str], *, agent_kind: str = "assistant") -> list[str]:
    if tools is None:
        return []
    if not isinstance(tools, list):
        raise AgentValidationError("tools must be a list of tool names")
    # adk_task agents draw from the curated ADK tool registry (read/deliverable/
    # memory/approval-gated-write); classic agents use the legacy REGISTRY.
    if agent_kind == "adk_task":
        from app.adk.registry import ADK_TOOL_REGISTRY

        valid = ADK_TOOL_REGISTRY
    else:
        valid = REGISTRY
    out: list[str] = []
    seen: set[str] = set()
    for name in tools:
        if not isinstance(name, str):
            raise AgentValidationError("tools must be a list of tool names")
        if name not in valid:
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


def _validate_agent_kind(kind: str) -> str:
    if kind not in AGENT_KINDS:
        raise AgentValidationError(
            f"agent_kind must be one of {', '.join(AGENT_KINDS)}"
        )
    return kind


def _validate_runtime(runtime: str) -> str:
    if runtime not in RUNTIMES:
        raise AgentValidationError(f"runtime must be one of {', '.join(RUNTIMES)}")
    return runtime


def _validate_visibility(vis: str) -> str:
    if vis not in VISIBILITIES:
        raise AgentValidationError(
            f"visibility must be one of {', '.join(VISIBILITIES)}"
        )
    return vis


def _validate_adk_config(cfg: Any) -> dict | None:
    if cfg is None:
        return None
    if not isinstance(cfg, dict):
        raise AgentValidationError("adk_config must be an object")
    # instruction is the ADK agent's system instruction; tools/output_schema
    # are optional. Keep validation light — the ADK tool allow-list is the
    # `tools` column (validated separately) and the runner filters by it.
    instruction = cfg.get("instruction")
    if instruction is not None and not isinstance(instruction, str):
        raise AgentValidationError("adk_config.instruction must be a string")
    return cfg


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
    """AGENT_BUILDER.md §2 — detail read; 404 unknown/cross-tenant.

    Sharing (ADK_AGENTS_DESIGN.md §3): if the agent is not found in the
    caller's own tenant, fall back to the audited platform-scope SHARED read
    — a `visibility='shared'` agent authored by any tenant is usable by all.
    Private agents stay strictly tenant-isolated (still 404 cross-tenant).
    """
    async with tenant_session(tenant_id) as db:
        await _provision_tenant(db, tenant_id)
        row = (
            await db.execute(
                sa.select(AgentDef).where(
                    AgentDef.tenant_id == tenant_id,
                    AgentDef.agent_id == agent_id,
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            return _detail_dict(row)
    # Not in the caller's tenant — try the shared platform scope.
    shared = await _load_shared_agent(agent_id)
    if shared is not None:
        return shared
    raise AgentNotFoundError("agent not found for this tenant")


async def _load_shared_agent(agent_id: str) -> dict | None:
    """Audited platform-scope read for a SHARED agent (ADK_AGENTS_DESIGN.md §3).

    Bypasses per-tenant RLS via admin_session — but ONLY returns agents whose
    visibility='shared'. This is the sole sanctioned cross-tenant read; a
    private agent is never returned here. Sharing exposes the DEFINITION only
    (not the creator's data).
    """
    from app.db import admin_session  # local import (maintenance-path session)

    async with admin_session() as db:
        row = (
            await db.execute(
                sa.select(AgentDef).where(
                    AgentDef.agent_id == agent_id,
                    AgentDef.visibility == "shared",
                    AgentDef.enabled.is_(True),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        detail = _detail_dict(row)
        detail["shared"] = True
        detail["authoring_tenant_id"] = row.tenant_id
        log.info(
            "shared agent read: agent=%s authoring_tenant=%s",
            agent_id,
            row.tenant_id,
        )
        return detail


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
        agent_kind = _validate_agent_kind(str(data.get("agent_kind", "assistant")))
        tools = _validate_tools(data.get("tools", []) or [], agent_kind=agent_kind)
        memory_policy = _validate_memory_policy(str(data.get("memory_policy", "off")))
        # When no explicit budget is given, default to the config default but
        # never above the tenant's own cap (user-* tenants cap below the config
        # default, so a fixed default would otherwise 400 every create).
        if data.get("budget_monthly_usd") is not None:
            budget = await _validate_budget(db, tenant_id, data["budget_monthly_usd"])
        else:
            tenant_cap, _ = await budget_mod.resolve_tenant_budget(db, tenant_id)
            budget = await _validate_budget(
                db, tenant_id, min(s.DEFAULT_BUDGET_MONTHLY_USD, tenant_cap)
            )
        enabled = bool(data.get("enabled", True))
        # An adk_task agent implies the adk runtime (and vice-versa default).
        default_runtime = "adk" if agent_kind == "adk_task" else "claude"
        runtime = _validate_runtime(str(data.get("runtime", default_runtime)))
        visibility = _validate_visibility(str(data.get("visibility", "private")))
        adk_config = _validate_adk_config(data.get("adk_config"))
        owner_user_id = data.get("owner_user_id")
        if owner_user_id is not None:
            owner_user_id = str(owner_user_id)

        row = AgentDef(
            tenant_id=tenant_id,
            agent_id=agent_id,
            system_prompt=system_prompt,
            model=model,
            tools=tools,
            budget_monthly_usd=budget,
            enabled=enabled,
            memory_policy=memory_policy,
            agent_kind=agent_kind,
            runtime=runtime,
            visibility=visibility,
            owner_user_id=owner_user_id,
            approval_state="draft",
            adk_config=adk_config,
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
        if "agent_kind" in patch:
            row.agent_kind = _validate_agent_kind(str(patch["agent_kind"]))
            changed.append("agent_kind")
        if "tools" in patch:
            # Validate against the registry implied by the effective kind
            # (patched kind wins; else the row's current kind).
            eff_kind = getattr(row, "agent_kind", "assistant") or "assistant"
            row.tools = _validate_tools(patch["tools"], agent_kind=eff_kind)
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
        if "runtime" in patch:
            row.runtime = _validate_runtime(str(patch["runtime"]))
            changed.append("runtime")
        if "visibility" in patch:
            # Sharing toggle (private ↔ shared). Any user may share their own
            # agent (internal-tool sharing, ADK_AGENTS_DESIGN.md §3).
            row.visibility = _validate_visibility(str(patch["visibility"]))
            changed.append("visibility")
        if "adk_config" in patch:
            row.adk_config = _validate_adk_config(patch["adk_config"])
            changed.append("adk_config")
        # approval_state is NOT directly patchable here: it only moves via the
        # governance flow (suggest → owner approve/reject). This prevents a
        # non-owner from self-approving an agent by PATCH.

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
