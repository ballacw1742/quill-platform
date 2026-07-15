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
from app.models import AgentDef, AgentVersion
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
# Hybrid Sensitivity Router (§8): the model lane an agent can be assigned.
# local = on-prem inference (sensitive data stays on the box; fail-safe
# default); frontier = Claude API (non-sensitive agents only).
MODEL_LANES = ("local", "frontier")

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


# Phase 5 (AUTHORING_MATURITY.md §2.3) — the mutable fields that are
# versioned/snapshotted/diffed/rolled-back. `tools` compares as ordered list.
VERSIONED_FIELDS = (
    "system_prompt",
    "model",
    "tools",
    "memory_policy",
    "budget_monthly_usd",
    "enabled",
)


def _detail_dict(a: AgentDef) -> dict[str, Any]:
    """AGENT_BUILDER.md §1 — the detail shape (superset of the A5 list dict).

    Additive ADK fields (ADK_AGENTS_DESIGN.md §1) let the builder UI render
    agent-kind/runtime/visibility/approval_state + adk_config; Phase 5 further
    extends it with `version` + `published`. All additive — existing consumers
    keep working (they read a subset)."""
    return {
        "agent_id": a.agent_id,
        "system_prompt": a.system_prompt,
        "model": a.model,
        "tools": list(a.tools or []),
        "memory_policy": a.memory_policy,
        "model_lane": getattr(a, "model_lane", "local") or "local",
        "budget_monthly_usd": float(a.budget_monthly_usd),
        "enabled": a.enabled,
        "is_seed": a.agent_id in SEED_AGENT_IDS,
        "agent_kind": getattr(a, "agent_kind", "assistant") or "assistant",
        "runtime": getattr(a, "runtime", "claude") or "claude",
        "owner_user_id": getattr(a, "owner_user_id", None),
        "visibility": getattr(a, "visibility", "private") or "private",
        "approval_state": getattr(a, "approval_state", "draft") or "draft",
        "adk_config": getattr(a, "adk_config", None),
        "version": int(getattr(a, "version", 1) or 1),
        "published": bool(getattr(a, "published", False)),
        "created_at": a.created_at,
    }


def _fields_of(a: AgentDef) -> dict[str, Any]:
    """The versioned field values of a live agent row."""
    return {
        "system_prompt": a.system_prompt,
        "model": a.model,
        "tools": list(a.tools or []),
        "memory_policy": a.memory_policy,
        "budget_monthly_usd": float(a.budget_monthly_usd),
        "enabled": a.enabled,
    }


def _snapshot_fields(v: AgentVersion) -> dict[str, Any]:
    """The versioned field values of a frozen snapshot row."""
    return {
        "system_prompt": v.system_prompt,
        "model": v.model,
        "tools": list(v.tools or []),
        "memory_policy": v.memory_policy,
        "budget_monthly_usd": float(v.budget_monthly_usd),
        "enabled": v.enabled,
    }


def _freeze(
    db,
    *,
    tenant_id: str,
    agent_id: str,
    version: int,
    fields: dict[str, Any],
    change_action: str,
    changed_fields: list[str],
    rolled_back_from: int | None = None,
) -> None:
    """Freeze a captured field snapshot into an immutable version row
    (AUTHORING_MATURITY.md §1.2). `fields` are the PRIOR (pre-mutation) values
    captured before the patch is applied. The forward metadata (change_action/
    changed_fields/rolled_back_from) describes the transition OUT of this
    version into the next, so the head can reconstruct its own metadata (§5).
    """
    db.add(
        AgentVersion(
            tenant_id=tenant_id,
            agent_id=agent_id,
            version=int(version),
            system_prompt=fields["system_prompt"],
            model=fields["model"],
            tools=list(fields["tools"] or []),
            memory_policy=fields["memory_policy"],
            budget_monthly_usd=fields["budget_monthly_usd"],
            enabled=fields["enabled"],
            change_action=change_action,
            changed_fields=list(changed_fields),
            rolled_back_from=rolled_back_from,
        )
    )


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


def _validate_model_lane(lane: str) -> str:
    if lane not in MODEL_LANES:
        raise AgentValidationError(
            f"model_lane must be one of {', '.join(MODEL_LANES)}"
        )
    return lane


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


def _emit_event(db, tenant_id: str, agent_id: str, type: str, payload: dict):
    """Generic Phase 5 event emitter (AUTHORING_MATURITY.md §4) — durable row
    in-tx, published post-commit by the caller."""
    ev = events_mod.make_event(
        tenant_id=tenant_id, agent_id=agent_id, type=type, payload=payload
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
        # Model lane (§8): fail-safe to 'local' when unspecified so a new agent
        # keeps data on-prem until explicitly promoted to the frontier lane.
        model_lane = _validate_model_lane(str(data.get("model_lane", "local")))
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
            model_lane=model_lane,
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

        # Phase 5 (AUTHORING_MATURITY.md §1.2): capture the PRIOR field values
        # + version BEFORE applying the patch, so the snapshot is faithful.
        prior_fields = _fields_of(row)
        prior_version = int(row.version)

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
        if "model_lane" in patch:
            row.model_lane = _validate_model_lane(str(patch["model_lane"]))
            changed.append("model_lane")
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
            # No-op update: no snapshot, no version bump (AUTHORING_MATURITY.md §3.6).
            return _detail_dict(row)

        # Phase 5: freeze the PRIOR state (captured above) into an immutable
        # snapshot tagged with the prior version, then bump the live version.
        _freeze(
            db,
            tenant_id=tenant_id,
            agent_id=agent_id,
            version=prior_version,
            fields=prior_fields,
            change_action="updated",
            changed_fields=changed,
        )
        row.version = prior_version + 1

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


# --- Phase 5: versioning / diff / rollback (AUTHORING_MATURITY.md) ------------


class VersionNotFoundError(LookupError):
    """404 — unknown version for this (tenant, agent)."""


async def _load_snapshots(db, tenant_id: str, agent_id: str) -> list[AgentVersion]:
    """All frozen snapshots for an agent, newest version first."""
    return list(
        (
            await db.execute(
                sa.select(AgentVersion)
                .where(
                    AgentVersion.tenant_id == tenant_id,
                    AgentVersion.agent_id == agent_id,
                )
                .order_by(AgentVersion.version.desc())
            )
        )
        .scalars()
        .all()
    )


def _head_meta(row: AgentDef, snapshots: list[AgentVersion]) -> dict[str, Any]:
    """Reconstruct the live head's forward metadata (AUTHORING_MATURITY.md §5):
    the snapshot of version N-1 carries the metadata of the transition into the
    current version N. No snapshot => the agent was never updated (created).
    """
    prev = int(row.version) - 1
    for snap in snapshots:
        if int(snap.version) == prev:
            return {
                "change_action": snap.change_action,
                "changed_fields": list(snap.changed_fields or []),
                "rolled_back_from": snap.rolled_back_from,
            }
    return {"change_action": "created", "changed_fields": ["*"], "rolled_back_from": None}


async def list_versions(
    tenant_id: str, agent_id: str, *, limit: int = 100, offset: int = 0
) -> dict:
    """AUTHORING_MATURITY.md §2.1 — newest-first history (live head + all
    snapshots). 404 unknown/cross-tenant agent."""
    async with tenant_session(tenant_id) as db:
        await _provision_tenant(db, tenant_id)
        row = await _load(db, tenant_id, agent_id)
        snapshots = await _load_snapshots(db, tenant_id, agent_id)

        items: list[dict[str, Any]] = []
        head_meta = _head_meta(row, snapshots)
        items.append(
            {
                "version": int(row.version),
                "change_action": head_meta["change_action"],
                "changed_fields": head_meta["changed_fields"],
                "rolled_back_from": head_meta["rolled_back_from"],
                "is_current": True,
                "created_at": row.created_at,
            }
        )
        for snap in snapshots:
            items.append(
                {
                    "version": int(snap.version),
                    "change_action": snap.change_action,
                    "changed_fields": list(snap.changed_fields or []),
                    "rolled_back_from": snap.rolled_back_from,
                    "is_current": False,
                    "created_at": snap.created_at,
                }
            )
        items.sort(key=lambda i: i["version"], reverse=True)
        total = len(items)
        page = items[offset : offset + limit]
        return {"items": page, "total": total, "limit": limit, "offset": offset}


async def _version_fields(
    db, tenant_id: str, agent_id: str, version: int, row: AgentDef
) -> dict[str, Any]:
    """The versioned field values for a given version number: the live row when
    version == row.version, else the frozen snapshot. Raises
    VersionNotFoundError if unknown."""
    if int(version) == int(row.version):
        return _fields_of(row)
    snap = (
        await db.execute(
            sa.select(AgentVersion).where(
                AgentVersion.tenant_id == tenant_id,
                AgentVersion.agent_id == agent_id,
                AgentVersion.version == int(version),
            )
        )
    ).scalar_one_or_none()
    if snap is None:
        raise VersionNotFoundError("version not found for this agent")
    return _snapshot_fields(snap)


async def get_version(tenant_id: str, agent_id: str, version: int) -> dict:
    """AUTHORING_MATURITY.md §2.2 — one version's full field snapshot. 404
    unknown agent OR unknown version."""
    async with tenant_session(tenant_id) as db:
        await _provision_tenant(db, tenant_id)
        row = await _load(db, tenant_id, agent_id)
        fields = await _version_fields(db, tenant_id, agent_id, version, row)
        created_at = row.created_at
        if int(version) != int(row.version):
            snap = (
                await db.execute(
                    sa.select(AgentVersion).where(
                        AgentVersion.tenant_id == tenant_id,
                        AgentVersion.agent_id == agent_id,
                        AgentVersion.version == int(version),
                    )
                )
            ).scalar_one()
            created_at = snap.created_at
        return {
            "agent_id": agent_id,
            "version": int(version),
            **fields,
            "is_current": int(version) == int(row.version),
            "created_at": created_at,
        }


async def diff_versions(
    tenant_id: str, agent_id: str, from_version: int, to_version: int
) -> dict:
    """AUTHORING_MATURITY.md §2.3 — field-level diff. Only differing fields
    appear in `changes`. 404 unknown agent/version."""
    async with tenant_session(tenant_id) as db:
        await _provision_tenant(db, tenant_id)
        row = await _load(db, tenant_id, agent_id)
        a = await _version_fields(db, tenant_id, agent_id, from_version, row)
        b = await _version_fields(db, tenant_id, agent_id, to_version, row)
        changes = []
        for field in VERSIONED_FIELDS:
            if a[field] != b[field]:
                changes.append({"field": field, "from": a[field], "to": b[field]})
        return {
            "agent_id": agent_id,
            "from_version": int(from_version),
            "to_version": int(to_version),
            "changes": changes,
        }


async def rollback_agent(tenant_id: str, agent_id: str, to_version: int) -> dict:
    """AUTHORING_MATURITY.md §2.4 — restore fields to `to_version` as a NEW
    version (never destructive). Seeds are never left disabled. Emits
    agent.rolledback. 404 unknown agent/version."""
    is_seed = agent_id in SEED_AGENT_IDS
    async with tenant_session(tenant_id) as db:
        await _provision_tenant(db, tenant_id)
        row = await _load(db, tenant_id, agent_id)

        target = await _version_fields(db, tenant_id, agent_id, to_version, row)

        prior_fields = _fields_of(row)
        prior_version = int(row.version)

        # Determine which fields actually change (for the event + snapshot meta).
        restored: list[str] = []
        for field in VERSIONED_FIELDS:
            new_val = target[field]
            # Seed protection: never restore a disabled state onto a seed (§2.4).
            if field == "enabled" and is_seed and not new_val:
                continue
            if prior_fields[field] != new_val:
                restored.append(field)

        if not restored:
            # Rolling back to an identical state is a no-op (no new version).
            return _detail_dict(row)

        # Freeze the prior live state, tagged as the transition that produced
        # the new (rolled-back) version.
        _freeze(
            db,
            tenant_id=tenant_id,
            agent_id=agent_id,
            version=prior_version,
            fields=prior_fields,
            change_action="rolledback",
            changed_fields=restored,
            rolled_back_from=int(to_version),
        )
        # Apply the restored fields.
        row.system_prompt = target["system_prompt"]
        row.model = target["model"]
        row.tools = list(target["tools"] or [])
        row.memory_policy = target["memory_policy"]
        row.budget_monthly_usd = target["budget_monthly_usd"]
        if not (is_seed and not target["enabled"]):
            row.enabled = target["enabled"]
        row.version = prior_version + 1
        new_version = int(row.version)

        ev = _emit_event(
            db,
            tenant_id,
            agent_id,
            "agent.rolledback",
            {
                "to_version": int(to_version),
                "new_version": new_version,
                "fields": restored,
            },
        )
        await db.flush()
        await db.refresh(row)
        detail = _detail_dict(row)
    await events_mod.emit([ev])
    return detail


async def set_published(tenant_id: str, agent_id: str, published: bool) -> dict:
    """AUTHORING_MATURITY.md §2.5 — toggle the tenant-scoped publish flag.
    Allowed on any agent (incl. seeds); never disables. Emits agent.published.
    404 unknown/cross-tenant."""
    async with tenant_session(tenant_id) as db:
        await _provision_tenant(db, tenant_id)
        row = await _load(db, tenant_id, agent_id)
        row.published = bool(published)
        ev = _emit_event(
            db,
            tenant_id,
            agent_id,
            "agent.published",
            {"published": bool(published), "version": int(row.version)},
        )
        await db.flush()
        await db.refresh(row)
        detail = _detail_dict(row)
    await events_mod.emit([ev])
    return detail


async def list_published(
    tenant_id: str, *, limit: int = 100, offset: int = 0
) -> dict:
    """AUTHORING_MATURITY.md §2.6 — the tenant's published agents as
    clone-source cards. Tenant-isolated (no cross-tenant leakage)."""
    async with tenant_session(tenant_id) as db:
        await _provision_tenant(db, tenant_id)
        total = (
            await db.execute(
                sa.select(sa.func.count())
                .select_from(AgentDef)
                .where(
                    AgentDef.tenant_id == tenant_id,
                    AgentDef.published.is_(True),
                )
            )
        ).scalar_one()
        rows = (
            (
                await db.execute(
                    sa.select(AgentDef)
                    .where(
                        AgentDef.tenant_id == tenant_id,
                        AgentDef.published.is_(True),
                    )
                    .order_by(AgentDef.agent_id)
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        items = [
            {
                "agent_id": a.agent_id,
                "version": int(a.version),
                "name": a.agent_id,
                "summary": f"Published agent (v{int(a.version)})",
                "system_prompt": a.system_prompt,
                "model": a.model,
                "tools": list(a.tools or []),
                "memory_policy": a.memory_policy,
                "budget_monthly_usd": float(a.budget_monthly_usd),
            }
            for a in rows
        ]
        return {"items": items, "total": int(total), "limit": limit, "offset": offset}
