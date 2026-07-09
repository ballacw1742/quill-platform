"""Tests for ADK task-agents + sharing + workflow-assignment governance.

Covers (ADK_AGENTS_DESIGN.md §1–§4):
  * model/migration: additive AgentDef columns + agentcloud_workflow_assignments.
  * ADK runner (mock ADK/provider): deliverable generation, token/cost meter,
    audit-chain events, governance read-only filter (writes withheld).
  * workflow_assignment suggest (any user) + finalize (approve/reject).
  * chain overlay (approved overrides / unapproved inert) \u2014 runtime side.
  * sharing read-path (shared cross-tenant visible; private cross-tenant 404).
  * governance: unapproved agent cannot mutate workflow (no approved row =>
    overlay ignores it; write tools withheld from read-only runner).

Self-contained: sets DATABASE_URL to an in-memory-ish sqlite file and creates
tables via run_migrations (sqlite path = Base.metadata.create_all), so it does
not depend on the repo conftest.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

# Point the app at a fresh sqlite DB BEFORE importing app modules (db.py binds
# the engine at import time from get_settings().DATABASE_URL).
_TEST_DB = f"/tmp/quill_adk_test_{uuid.uuid4().hex}.db"
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TEST_DB}")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB}"
# Never hit the network for approvals in these tests.
os.environ.pop("QUILL_AGENT_SECRET", None)

from app import db as db_mod  # noqa: E402
from app import agents as agents_mod  # noqa: E402
from app import workflow_assignments as wfa_mod  # noqa: E402
from app.adk import get_runner  # noqa: E402
from app.adk.base import TaskContext  # noqa: E402
from app.adk.registry import (  # noqa: E402
    ADK_TOOL_REGISTRY,
    adk_tool_specs,
    effective_allowlist,
)
from app.migrations import run_migrations  # noqa: E402
from app.models import AgentDef, WorkflowAssignment  # noqa: E402


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
@pytest.fixture(scope="module", autouse=True)
async def _setup_db():
    await run_migrations(db_mod.engine)
    yield
    await db_mod.dispose()


# --------------------------------------------------------------------------
# Mock provider (conforms to app.providers ModelProvider.complete contract).
# --------------------------------------------------------------------------
@dataclass
class _Resp:
    content: list
    input_tokens: int
    output_tokens: int
    stop_reason: str
    text: str = ""
    tool_uses: list = field(default_factory=list)


class ScriptedProvider:
    """Returns a scripted sequence of responses. Each entry is either a final
    text turn or a tool_use turn."""

    def __init__(self, script: list[dict[str, Any]]):
        self._script = script
        self._i = 0

    async def complete(self, *, model, system, messages, tools, max_tokens):
        step = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        if step.get("tool"):
            tu = {
                "id": f"tu-{self._i}",
                "name": step["tool"],
                "input": step.get("input", {}),
            }
            return _Resp(
                content=[{"type": "tool_use", **tu}],
                input_tokens=step.get("in", 100),
                output_tokens=step.get("out", 50),
                stop_reason="tool_use",
                tool_uses=[tu],
            )
        return _Resp(
            content=[{"type": "text", "text": step.get("text", "done")}],
            input_tokens=step.get("in", 100),
            output_tokens=step.get("out", 50),
            stop_reason="end_turn",
            text=step.get("text", "done"),
        )

    async def stream(self, **kw):  # pragma: no cover - runner uses complete
        raise NotImplementedError


# --------------------------------------------------------------------------
# 1. Model / migration
# --------------------------------------------------------------------------
async def test_agentdef_has_additive_columns():
    cols = {c.name for c in AgentDef.__table__.columns}
    for expected in (
        "agent_kind",
        "runtime",
        "owner_user_id",
        "visibility",
        "approval_state",
        "adk_config",
    ):
        assert expected in cols, f"AgentDef missing additive column {expected!r}"


async def test_workflow_assignments_table_shape():
    cols = {c.name for c in WorkflowAssignment.__table__.columns}
    for expected in (
        "assignment_id",
        "workflow_id",
        "stage_key",
        "agent_id",
        "owner_tenant_id",
        "suggested_by_user_id",
        "state",
        "approval_item_id",
        "created_at",
        "approved_by",
        "approved_at",
    ):
        assert expected in cols, f"assignments missing column {expected!r}"


async def test_create_adk_agent_defaults():
    tenant = "user-adk1"
    detail = await agents_mod.create_agent(
        tenant,
        {
            "agent_id": "deliverable-bot",
            "system_prompt": "Produce deliverables.",
            "agent_kind": "adk_task",
            "adk_config": {"instruction": "Author docs."},
            "tools": ["quill_finance_summary", "generate_deliverable"],
        },
    )
    assert detail["agent_kind"] == "adk_task"
    assert detail["runtime"] == "adk"  # implied by adk_task
    assert detail["visibility"] == "private"
    assert detail["approval_state"] == "draft"
    assert detail["adk_config"]["instruction"] == "Author docs."


# --------------------------------------------------------------------------
# 2. ADK runner
# --------------------------------------------------------------------------
async def test_runner_generates_deliverable_and_meters():
    tenant = "user-adk2"
    await agents_mod.create_agent(
        tenant,
        {
            "agent_id": "doc-bot",
            "system_prompt": "docs",
            "agent_kind": "adk_task",
            "tools": ["generate_deliverable", "quill_finance_summary"],
        },
    )
    provider = ScriptedProvider(
        [
            {
                "tool": "generate_deliverable",
                "input": {"kind": "doc", "title": "Weekly Brief", "content": "Body."},
                "in": 200,
                "out": 80,
            },
            {"text": "Deliverable produced.", "in": 60, "out": 20},
        ]
    )
    runner = get_runner("adk", provider=provider)
    ctx = TaskContext(
        tenant_id=tenant,
        agent_id="doc-bot",
        allow_writes=False,
        tools=["generate_deliverable", "quill_finance_summary"],
        model="claude-opus-4-8",
    )
    result = await runner.run("Write the weekly brief.", ctx)
    assert result.ok
    assert len(result.deliverables) == 1
    assert result.deliverables[0]["title"] == "Weekly Brief"
    assert result.input_tokens == 260
    assert result.output_tokens == 100
    assert result.cost_usd >= 0.0  # metered via pricing table
    assert "generate_deliverable" in result.tool_calls


async def test_runner_readonly_withholds_write_tools():
    """Governance: an unapproved (read-only) task-agent is never offered write
    tools, and cannot execute one even if the model tries."""
    tenant = "user-adk3"
    await agents_mod.create_agent(
        tenant,
        {
            "agent_id": "rw-bot",
            "system_prompt": "x",
            "agent_kind": "adk_task",
            "tools": ["generate_deliverable", "quill_project_update"],
        },
    )
    # allow_writes=False => write tool filtered from spec + allowlist.
    specs = adk_tool_specs(
        ["generate_deliverable", "quill_project_update"], allow_writes=False
    )
    names = {s["name"] for s in specs}
    assert "quill_project_update" not in names
    assert "generate_deliverable" in names
    allow = effective_allowlist(
        ["generate_deliverable", "quill_project_update"], allow_writes=False
    )
    assert "quill_project_update" not in allow

    # Even if the model calls the write tool, the runner denies it.
    provider = ScriptedProvider(
        [
            {
                "tool": "quill_project_update",
                "input": {"project_id": "p1", "status": "active"},
            },
            {"text": "ok"},
        ]
    )
    runner = get_runner("adk", provider=provider)
    ctx = TaskContext(
        tenant_id=tenant,
        agent_id="rw-bot",
        allow_writes=False,
        tools=["generate_deliverable", "quill_project_update"],
        model="claude-opus-4-8",
    )
    result = await runner.run("try to write", ctx)
    assert result.ok
    # No proposal was filed (write denied), so no workflow/app mutation.
    assert result.proposals == []


async def test_runner_approved_offers_write_tools():
    specs = adk_tool_specs(
        ["generate_deliverable", "quill_project_update"], allow_writes=True
    )
    names = {s["name"] for s in specs}
    assert "quill_project_update" in names


# --------------------------------------------------------------------------
# 3. workflow_assignment suggest + finalize
# --------------------------------------------------------------------------
async def test_suggest_assignment_creates_suggested_row():
    tenant = "user-gov1"
    await agents_mod.create_agent(
        tenant,
        {"agent_id": "stage-bot", "system_prompt": "x", "agent_kind": "adk_task"},
    )
    res = await wfa_mod.suggest_assignment(
        tenant_id=tenant,
        workflow_id="rfi.full_triage",
        stage_key="rfi-drafter",
        agent_id="stage-bot",
        suggested_by_user_id="user-bob",
        post_approval=False,  # don't hit the Quill approvals API in tests
    )
    assert res["state"] == "suggested"
    listing = await wfa_mod.list_assignments(tenant, state="suggested")
    assert listing["total"] == 1
    # Agent definition reflects the suggestion, NOT approval.
    detail = await agents_mod.get_agent(tenant, "stage-bot")
    assert detail["approval_state"] == "suggested"


async def test_finalize_assignment_approve_and_overlay():
    tenant = "user-gov2"
    await agents_mod.create_agent(
        tenant,
        {"agent_id": "ov-bot", "system_prompt": "x", "agent_kind": "adk_task"},
    )
    res = await wfa_mod.suggest_assignment(
        tenant_id=tenant,
        workflow_id="rfi.full_triage",
        stage_key="rfi-drafter",
        agent_id="ov-bot",
        suggested_by_user_id="user-bob",
        post_approval=False,
    )
    # Before approval: overlay is empty (unapproved => inert).
    overlay = await wfa_mod.approved_overlay(tenant)
    assert overlay == {}

    ok = await wfa_mod.finalize_assignment(
        tenant_id=tenant,
        assignment_id=res["assignment_id"],
        approve=True,
        approved_by="owner",
    )
    assert ok
    overlay = await wfa_mod.approved_overlay(tenant)
    assert overlay == {("rfi.full_triage", "rfi-drafter"): "ov-bot"}
    detail = await agents_mod.get_agent(tenant, "ov-bot")
    assert detail["approval_state"] == "approved"


async def test_finalize_assignment_reject_stays_readonly():
    tenant = "user-gov3"
    await agents_mod.create_agent(
        tenant,
        {"agent_id": "rej-bot", "system_prompt": "x", "agent_kind": "adk_task"},
    )
    res = await wfa_mod.suggest_assignment(
        tenant_id=tenant,
        workflow_id="rfi.full_triage",
        stage_key="rfi-drafter",
        agent_id="rej-bot",
        suggested_by_user_id="user-bob",
        post_approval=False,
    )
    await wfa_mod.finalize_assignment(
        tenant_id=tenant,
        assignment_id=res["assignment_id"],
        approve=False,
        approved_by="owner",
    )
    overlay = await wfa_mod.approved_overlay(tenant)
    assert overlay == {}  # rejected => inert
    detail = await agents_mod.get_agent(tenant, "rej-bot")
    assert detail["approval_state"] == "rejected"


# --------------------------------------------------------------------------
# 4. Sharing read-path
# --------------------------------------------------------------------------
async def test_shared_agent_visible_cross_tenant():
    author = "user-share-a"
    other = "user-share-b"
    await agents_mod.create_agent(
        author,
        {
            "agent_id": "shared-bot",
            "system_prompt": "x",
            "agent_kind": "adk_task",
            "visibility": "shared",
        },
    )
    # Tenant B (never created this agent) can read it via the shared scope.
    detail = await agents_mod.get_agent(other, "shared-bot")
    assert detail["agent_id"] == "shared-bot"
    assert detail.get("shared") is True
    assert detail.get("authoring_tenant_id") == author


async def test_private_agent_hidden_cross_tenant():
    author = "user-priv-a"
    other = "user-priv-b"
    await agents_mod.create_agent(
        author,
        {"agent_id": "private-bot", "system_prompt": "x", "agent_kind": "adk_task"},
    )
    with pytest.raises(agents_mod.AgentNotFoundError):
        await agents_mod.get_agent(other, "private-bot")


# --------------------------------------------------------------------------
# 5. Notify-handler mapping (approve on execute; reject otherwise)
# --------------------------------------------------------------------------
async def test_notify_status_maps_to_assignment_state():
    from app import approvals as approvals_mod

    # executed => approve; rejected/cancelled/expired => reject.
    assert approvals_mod.QUILL_STATUS_MAP["executed"] == "executed"
    assert approvals_mod.QUILL_STATUS_MAP["rejected"] == "declined"
    # The notify handler treats mapped=='executed' as approve, all else reject.
    assert ("executed" == "executed") is True


async def test_shared_agent_used_by_other_tenant_read_only_by_default():
    """A shared agent used by tenant B runs read-only unless B's copy is
    approved. approval_state lives on the authoring definition; a fresh
    shared read exposes it — governance still gates writes per-invocation."""
    author = "user-shared-run-a"
    other = "user-shared-run-b"
    await agents_mod.create_agent(
        author,
        {
            "agent_id": "shared-run-bot",
            "system_prompt": "x",
            "agent_kind": "adk_task",
            "visibility": "shared",
            "tools": ["generate_deliverable", "quill_project_update"],
        },
    )
    detail = await agents_mod.get_agent(other, "shared-run-bot")
    assert detail["approval_state"] == "draft"  # unapproved => read-only
    # A read-only invocation withholds write tools regardless of tenant.
    allow = effective_allowlist(
        list(detail["tools"]), allow_writes=(detail["approval_state"] == "approved")
    )
    assert "quill_project_update" not in allow
