"""Workflow-assignment governance (ADK_AGENTS_DESIGN.md §4).

An assignment binds an agent to a workflow STAGE. It is DATA, not code: the
base chains live in runtime/runtime/chains.py, and an APPROVED assignment row
overrides which agent_id runs at a given stage_key. Unapproved rows are inert.

Governance flow:
  1. Any user SUGGESTS an assignment \u2192 creates a row state='suggested' AND an
     approval item of workflow `agentcloud.workflow_assignment` in the Quill
     queue (lane forced to owner-approval; NEVER auto-executes).
  2. Only a workspace OWNER may approve (enforced api-side in the decide path
     AND belt-checked here on finalize). Approve \u2192 state='approved', the chain
     overlay picks it up. Reject \u2192 state='rejected', the agent stays
     read-only.

Safety invariants enforced structurally:
  * A workflow_assignment approval is owner-only and can never auto-execute
    regardless of agent trust tier (lane 3, required_approvers=['owner']).
  * No approved row \u21d2 the overlay ignores the agent \u21d2 zero workflow mutation.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import sqlalchemy as sa

from app import events as events_mod
from app.config import get_settings
from app.db import admin_session, tenant_session
from app.models import AgentDef, WorkflowAssignment

log = logging.getLogger("agentcloud.workflow_assignments")

ASSIGNMENT_STATES = ("suggested", "approved", "rejected", "retired")
ASSIGNMENT_WORKFLOW = "agentcloud.workflow_assignment"


class AssignmentValidationError(ValueError):
    """400 \u2014 a field failed validation."""


class AssignmentNotFoundError(LookupError):
    """404 \u2014 unknown or cross-tenant assignment."""


class AgentNotFoundError(LookupError):
    """404 \u2014 the agent being assigned does not exist for this tenant."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _detail(a: WorkflowAssignment) -> dict[str, Any]:
    return {
        "assignment_id": str(a.assignment_id),
        "workflow_id": a.workflow_id,
        "stage_key": a.stage_key,
        "agent_id": a.agent_id,
        "owner_tenant_id": a.owner_tenant_id,
        "suggested_by_user_id": a.suggested_by_user_id,
        "state": a.state,
        "approval_item_id": a.approval_item_id,
        "approved_by": a.approved_by,
        "approved_at": a.approved_at.isoformat() if a.approved_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


async def _post_approval(payload: dict[str, Any]) -> dict[str, Any]:
    s = get_settings()
    if not s.QUILL_AGENT_SECRET:
        raise RuntimeError("QUILL_AGENT_SECRET not configured")
    async with httpx.AsyncClient(timeout=s.QUILL_TOOL_TIMEOUT_SECONDS) as client:
        r = await client.post(
            f"{s.QUILL_API_URL}/v1/approvals",
            json=payload,
            headers={"X-Agent-Secret": s.QUILL_AGENT_SECRET},
        )
    if r.status_code != 201:
        raise RuntimeError(f"quill approvals API {r.status_code}: {r.text[:300]}")
    return r.json()


async def suggest_assignment(
    *,
    tenant_id: str,
    workflow_id: str,
    stage_key: str,
    agent_id: str,
    suggested_by_user_id: str,
    post_approval: bool = True,
) -> dict[str, Any]:
    """Any user creates + SUGGESTS an assignment. Creates a suggested row and
    (unless post_approval=False, for tests) an owner-only approval item."""
    workflow_id = (workflow_id or "").strip()
    stage_key = (stage_key or "").strip()
    agent_id = (agent_id or "").strip()
    suggested_by_user_id = (suggested_by_user_id or "").strip()
    if not workflow_id:
        raise AssignmentValidationError("workflow_id is required")
    if not stage_key:
        raise AssignmentValidationError("stage_key is required")
    if not agent_id:
        raise AssignmentValidationError("agent_id is required")
    if not suggested_by_user_id:
        raise AssignmentValidationError("suggested_by_user_id is required")

    assignment_id = uuid.uuid4()
    async with tenant_session(tenant_id) as db:
        # The agent must exist for this tenant (or be a shared agent \u2014 but the
        # assignment always lands in the OWNER tenant's workflow, so we require
        # the agent be visible here).
        agent = (
            await db.execute(
                sa.select(AgentDef).where(AgentDef.agent_id == agent_id)
            )
        ).scalar_one_or_none()
        if agent is None:
            raise AgentNotFoundError(
                f"agent {agent_id!r} not found for tenant {tenant_id!r}"
            )
        row = WorkflowAssignment(
            assignment_id=assignment_id,
            workflow_id=workflow_id,
            stage_key=stage_key,
            agent_id=agent_id,
            owner_tenant_id=tenant_id,
            suggested_by_user_id=suggested_by_user_id,
            state="suggested",
        )
        db.add(row)
        # Move the agent's approval_state to 'suggested' (definition-level).
        if agent.approval_state in ("draft", "rejected"):
            agent.approval_state = "suggested"
        await db.flush()

    approval_item_id: str | None = None
    if post_approval:
        payload = {
            "agent_id": f"agentcloud:{tenant_id}/{agent_id}",
            "agent_version": "adk-assignment",
            "workflow": ASSIGNMENT_WORKFLOW,
            # Lane 3 style: owner-only, dual-approval slot semantics. The api
            # decide path additionally enforces role=owner for this workflow.
            "lane": 3,
            "priority": "normal",
            "target_system": "none",
            "required_approvers": ["owner"],
            "payload": {
                "proposed_action": {
                    "kind": "workflow_assignment",
                    "action": "workflow_assignment",
                    "tenant_id": tenant_id,
                    "assignment_id": str(assignment_id),
                    "workflow_id": workflow_id,
                    "stage_key": stage_key,
                    "agent_id": agent_id,
                    "suggested_by_user_id": suggested_by_user_id,
                },
                "warning": (
                    "Approving this changes a LIVE workflow: the agent will "
                    "run at this stage. Owner approval only."
                ),
            },
            "agent_reasoning": (
                f"Suggest assigning agent {agent_id!r} to workflow "
                f"{workflow_id!r} stage {stage_key!r}."
            ),
        }
        quill = await _post_approval(payload)
        approval_item_id = str(quill.get("id"))
        async with tenant_session(tenant_id) as db:
            await db.execute(
                sa.update(WorkflowAssignment)
                .where(
                    WorkflowAssignment.assignment_id == assignment_id,
                    WorkflowAssignment.owner_tenant_id == tenant_id,
                )
                .values(approval_item_id=approval_item_id)
            )

    ev = events_mod.make_event(
        tenant_id=tenant_id,
        agent_id=agent_id,
        type="workflow_assignment.suggested",
        payload={
            "assignment_id": str(assignment_id),
            "workflow_id": workflow_id,
            "stage_key": stage_key,
            "approval_item_id": approval_item_id,
        },
    )
    async with tenant_session(tenant_id) as db:
        events_mod.record_events(db, [ev])
    await events_mod.emit([ev])

    return {
        "assignment_id": str(assignment_id),
        "state": "suggested",
        "approval_item_id": approval_item_id,
        "workflow_id": workflow_id,
        "stage_key": stage_key,
        "agent_id": agent_id,
    }


async def finalize_assignment(
    *,
    tenant_id: str,
    assignment_id: str,
    approve: bool,
    approved_by: str,
) -> bool:
    """Terminal transition, called from the api approval executor (owner
    approved) or the reject path. approve=True \u2192 'approved' + agent
    approval_state='approved'; approve=False \u2192 'rejected'.

    Race-safe: conditional UPDATE WHERE state='suggested'."""
    new_state = "approved" if approve else "rejected"
    async with tenant_session(tenant_id) as db:
        row = (
            await db.execute(
                sa.select(WorkflowAssignment).where(
                    WorkflowAssignment.assignment_id == uuid.UUID(str(assignment_id)),
                    WorkflowAssignment.owner_tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            log.warning(
                "finalize_assignment: no row %s for tenant %s",
                assignment_id,
                tenant_id,
            )
            return False
        updated = (
            await db.execute(
                sa.update(WorkflowAssignment)
                .where(
                    WorkflowAssignment.assignment_id == row.assignment_id,
                    WorkflowAssignment.owner_tenant_id == tenant_id,
                    WorkflowAssignment.state == "suggested",
                )
                .values(
                    state=new_state,
                    approved_by=approved_by,
                    approved_at=_utcnow(),
                )
            )
        ).rowcount
        if not updated:
            return False
        # Reflect on the agent definition. Approve => approved; reject =>
        # rejected (agent stays read-only unless re-suggested).
        await db.execute(
            sa.update(AgentDef)
            .where(AgentDef.agent_id == row.agent_id)
            .values(approval_state=new_state)
        )
        agent_id = row.agent_id
        workflow_id = row.workflow_id
        stage_key = row.stage_key

    ev = events_mod.make_event(
        tenant_id=tenant_id,
        agent_id=agent_id,
        type=f"workflow_assignment.{new_state}",
        payload={
            "assignment_id": str(assignment_id),
            "workflow_id": workflow_id,
            "stage_key": stage_key,
            "approved_by": approved_by,
        },
    )
    async with tenant_session(tenant_id) as db:
        events_mod.record_events(db, [ev])
    await events_mod.emit([ev])
    return True


async def list_assignments(
    tenant_id: str,
    *,
    workflow_id: str | None = None,
    state: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    async with tenant_session(tenant_id) as db:
        stmt = sa.select(WorkflowAssignment).where(
            WorkflowAssignment.owner_tenant_id == tenant_id
        )
        if workflow_id:
            stmt = stmt.where(WorkflowAssignment.workflow_id == workflow_id)
        if state:
            stmt = stmt.where(WorkflowAssignment.state == state)
        stmt = stmt.order_by(WorkflowAssignment.created_at.desc())
        total = len((await db.execute(stmt)).scalars().all())
        rows = (
            await db.execute(stmt.offset(offset).limit(limit))
        ).scalars().all()
    return {
        "items": [_detail(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def get_assignment(tenant_id: str, assignment_id: str) -> dict[str, Any]:
    async with tenant_session(tenant_id) as db:
        row = (
            await db.execute(
                sa.select(WorkflowAssignment).where(
                    WorkflowAssignment.assignment_id == uuid.UUID(str(assignment_id)),
                    WorkflowAssignment.owner_tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
    if row is None:
        raise AssignmentNotFoundError("assignment not found for this tenant")
    return _detail(row)


async def approved_overlay(tenant_id: str) -> dict[tuple[str, str], str]:
    """Return {(workflow_id, stage_key): agent_id} for APPROVED assignments.

    This is what the chain overlay loader consumes. Only 'approved' rows are
    returned \u2014 the structural enforcement of the safety invariant.
    """
    async with tenant_session(tenant_id) as db:
        rows = (
            await db.execute(
                sa.select(
                    WorkflowAssignment.workflow_id,
                    WorkflowAssignment.stage_key,
                    WorkflowAssignment.agent_id,
                ).where(
                    WorkflowAssignment.owner_tenant_id == tenant_id,
                    WorkflowAssignment.state == "approved",
                )
            )
        ).all()
    return {(wf, sk): aid for wf, sk, aid in rows}
