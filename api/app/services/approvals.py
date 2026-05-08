"""Approval Queue business logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import (
    AGENT_FLEET,
    ApprovalStatus,
    AuthMethod,
    Decision,
    ExecutionResult,
    Lane,
    Priority,
    UserRole,
)
from app.models import ApprovalItem, ApprovalRecord, User
from app.services import audit as audit_svc
from app.services.realtime import broadcaster

# SLA windows per the spec, in hours.
SLA_HOURS_BY_LANE: dict[int, int] = {
    Lane.AUTO.value: 1,
    Lane.SINGLE.value: 8,
    Lane.DUAL.value: 24,
}
SLA_HOURS_CRITICAL_PATH = 4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _utcnow() -> datetime:
    return datetime.now(UTC)


def compute_sla_due(lane: int, priority: str, now: datetime | None = None) -> datetime:
    base = SLA_HOURS_BY_LANE.get(lane, 8)
    if priority == Priority.CRITICAL_PATH.value:
        base = min(base, SLA_HOURS_CRITICAL_PATH)
    return (now or _utcnow()) + timedelta(hours=base)


def required_approvers_for_lane(lane: int, override: list[str] | None = None) -> list[str]:
    if override:
        return override
    if lane == Lane.AUTO.value:
        return []  # auto-execute
    if lane == Lane.SINGLE.value:
        return [UserRole.OWNER.value]
    if lane == Lane.DUAL.value:
        return [UserRole.OWNER.value, UserRole.PARTNER.value]
    return [UserRole.OWNER.value]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
async def create_approval(
    session: AsyncSession,
    *,
    payload: dict[str, Any],
    actor: str,
) -> ApprovalItem:
    """Persist a new ApprovalItem and chain an audit event."""
    if payload.get("agent_id") not in AGENT_FLEET:
        # Allow but flag — keeps this resilient if fleet changes faster than enums.
        # No raise; agents may be registered ad-hoc.
        pass

    lane = int(payload.get("lane") or Lane.SINGLE.value)
    priority = payload.get("priority") or Priority.NORMAL.value

    item = ApprovalItem(
        agent_id=payload["agent_id"],
        agent_version=payload.get("agent_version") or "0.0.0",
        workflow=payload["workflow"],
        lane=lane,
        priority=priority,
        target_system=payload.get("target_system") or "none",
        api_call=payload.get("api_call"),
        payload=payload.get("payload") or {},
        source_artifacts=payload.get("source_artifacts") or [],
        citations=payload.get("citations") or [],
        agent_confidence=float(payload.get("agent_confidence") or 0.0),
        agent_reasoning=payload.get("agent_reasoning"),
        agent_model=payload.get("agent_model"),
        agent_prompt_version=payload.get("agent_prompt_version"),
        agent_input_hash=payload.get("agent_input_hash"),
        agent_output_hash=payload.get("agent_output_hash"),
        required_approvers=required_approvers_for_lane(lane, payload.get("required_approvers")),
        sla_due_at=compute_sla_due(lane, priority),
        expires_at=payload.get("expires_at"),
        status=ApprovalStatus.PENDING.value,
    )
    session.add(item)
    await session.flush()

    entry = await audit_svc.record_event(
        session,
        event_type="approval.created",
        actor=actor,
        approval_item_id=item.id,
        payload={
            "agent_id": item.agent_id,
            "workflow": item.workflow,
            "lane": item.lane,
            "priority": item.priority,
            "agent_confidence": item.agent_confidence,
        },
    )
    item.audit_hash = entry.hash
    item.prev_audit_hash = entry.prev_hash
    await session.flush()

    # Lane 1 (auto) executes immediately, no human signature required.
    if item.lane == Lane.AUTO.value:
        await execute_approval(session, item.id, actor=actor)
        await session.refresh(item)

    await session.commit()
    await broadcaster.publish({"type": "approval.created", "id": item.id, "status": item.status})
    return item


# ---------------------------------------------------------------------------
# Decide
# ---------------------------------------------------------------------------
async def decide_approval(
    session: AsyncSession,
    *,
    approval_id: str,
    approver: User,
    decision: Decision,
    edits: dict[str, Any] | None = None,
    rejection_reason: str | None = None,
    auth_evidence: str | None = None,
    auth_method: AuthMethod = AuthMethod.DEV_TOKEN,
    escalate_to_lane: int | None = None,
) -> ApprovalItem:
    item = await session.get(ApprovalItem, approval_id)
    if item is None:
        raise LookupError(f"approval {approval_id} not found")
    if item.status != ApprovalStatus.PENDING.value:
        raise ValueError(f"approval {approval_id} is not pending (status={item.status})")
    if item.litigation_hold:
        raise PermissionError("approval is under litigation hold")

    # Authority check: approver's role must be one of required_approvers (case-insensitive).
    needed = {r.lower() for r in (item.required_approvers or [])}
    if needed and approver.role.lower() not in needed and approver.role != UserRole.OWNER.value:
        # Owner is a super-role that can sign on any required slot they hold.
        if approver.role.lower() not in needed:
            raise PermissionError(
                f"role {approver.role} not authorized for lane {item.lane}; "
                f"required: {sorted(needed)}"
            )

    # Load existing records (async-safe explicit query, avoid lazy relationship IO).
    existing_records_res = await session.execute(
        select(ApprovalRecord).where(ApprovalRecord.approval_item_id == item.id)
    )
    existing_records = list(existing_records_res.scalars().all())

    # Has this approver already signed?
    for r in existing_records:
        if r.approver_id == approver.id and r.decision in (
            Decision.APPROVE.value,
            Decision.EDIT_THEN_APPROVE.value,
        ):
            raise ValueError("approver has already signed")

    record = ApprovalRecord(
        approval_item_id=item.id,
        approver_id=approver.id,
        approver_role=approver.role,
        decision=decision.value,
        edits=edits,
        rejection_reason=rejection_reason,
        auth_method=auth_method.value,
        auth_evidence=auth_evidence,
    )
    session.add(record)
    await session.flush()

    audit_payload = {
        "decision": decision.value,
        "approver_id": approver.id,
        "approver_role": approver.role,
        "auth_method": auth_method.value,
    }
    if edits:
        audit_payload["edits"] = edits
    if rejection_reason:
        audit_payload["rejection_reason"] = rejection_reason

    entry = await audit_svc.record_event(
        session,
        event_type=f"approval.decision.{decision.value}",
        actor=approver.id,
        approval_item_id=item.id,
        payload=audit_payload,
    )
    item.prev_audit_hash = item.audit_hash
    item.audit_hash = entry.hash

    # Apply state transition
    if decision == Decision.REJECT:
        item.status = ApprovalStatus.REJECTED.value
    elif decision == Decision.ESCALATE:
        new_lane = escalate_to_lane or min(Lane.DUAL.value, item.lane + 1)
        item.lane = new_lane
        item.required_approvers = required_approvers_for_lane(new_lane)
        item.sla_due_at = compute_sla_due(new_lane, item.priority)
        item.status = ApprovalStatus.PENDING.value  # stays pending under new lane
        await session.commit()
        await broadcaster.publish(
            {"type": "approval.escalated", "id": item.id, "lane": new_lane}
        )
        return item
    else:  # approve / edit_then_approve
        if decision == Decision.EDIT_THEN_APPROVE and edits:
            merged = {**item.payload, **edits}
            item.payload = merged
        # Count approve signatures by required role coverage.
        all_records = existing_records + [record]
        signed_roles = {
            r.approver_role.lower()
            for r in all_records
            if r.decision in (Decision.APPROVE.value, Decision.EDIT_THEN_APPROVE.value)
        }
        required = {r.lower() for r in (item.required_approvers or [])}
        if required.issubset(signed_roles) or not required:
            item.status = ApprovalStatus.APPROVED.value

    await session.commit()
    await broadcaster.publish(
        {"type": "approval.decided", "id": item.id, "status": item.status, "decision": decision.value}
    )

    if item.status == ApprovalStatus.APPROVED.value:
        await execute_approval(session, item.id, actor=approver.id)
        await session.refresh(item)

    return item


# ---------------------------------------------------------------------------
# Execute (Sprint 1 stub)
# ---------------------------------------------------------------------------
async def execute_approval(
    session: AsyncSession, approval_id: str, *, actor: str
) -> ApprovalItem:
    """Sprint 1 stub: marks executed and records audit event. Idempotent."""
    item = await session.get(ApprovalItem, approval_id)
    if item is None:
        raise LookupError(f"approval {approval_id} not found")
    if item.status == ApprovalStatus.EXECUTED.value:
        return item
    if item.status not in (ApprovalStatus.APPROVED.value, ApprovalStatus.PENDING.value):
        raise ValueError(f"cannot execute from status={item.status}")

    item.status = ApprovalStatus.EXECUTED.value
    item.executed_at = _utcnow()
    item.execution_result = ExecutionResult.DRY_RUN.value  # Sprint 1 — no real side-effects
    item.external_ref = f"sprint1-stub:{item.id}"

    entry = await audit_svc.record_event(
        session,
        event_type="approval.executed",
        actor=actor,
        approval_item_id=item.id,
        payload={
            "execution_result": item.execution_result,
            "external_ref": item.external_ref,
            "target_system": item.target_system,
        },
    )
    item.prev_audit_hash = item.audit_hash
    item.audit_hash = entry.hash

    await session.commit()
    await broadcaster.publish(
        {"type": "approval.executed", "id": item.id, "status": item.status}
    )
    return item


# ---------------------------------------------------------------------------
# Cancel / Hold / Escalate helpers
# ---------------------------------------------------------------------------
async def cancel_approval(
    session: AsyncSession, approval_id: str, *, actor: str, reason: str | None = None
) -> ApprovalItem:
    item = await session.get(ApprovalItem, approval_id)
    if item is None:
        raise LookupError(f"approval {approval_id} not found")
    if item.status != ApprovalStatus.PENDING.value:
        raise ValueError(f"cannot cancel from status={item.status}")
    item.status = ApprovalStatus.CANCELLED.value

    entry = await audit_svc.record_event(
        session,
        event_type="approval.cancelled",
        actor=actor,
        approval_item_id=item.id,
        payload={"reason": reason},
    )
    item.prev_audit_hash = item.audit_hash
    item.audit_hash = entry.hash
    await session.commit()
    await broadcaster.publish({"type": "approval.cancelled", "id": item.id})
    return item


async def suspend_for_litigation_hold(
    session: AsyncSession, approval_id: str, *, actor: str, reason: str
) -> ApprovalItem:
    item = await session.get(ApprovalItem, approval_id)
    if item is None:
        raise LookupError(f"approval {approval_id} not found")
    item.litigation_hold = True
    item.suspended_reason = reason
    if item.status == ApprovalStatus.PENDING.value:
        item.status = ApprovalStatus.SUSPENDED.value

    entry = await audit_svc.record_event(
        session,
        event_type="approval.litigation_hold",
        actor=actor,
        approval_item_id=item.id,
        payload={"reason": reason},
    )
    item.prev_audit_hash = item.audit_hash
    item.audit_hash = entry.hash
    await session.commit()
    await broadcaster.publish({"type": "approval.held", "id": item.id})
    return item


async def list_pending(
    session: AsyncSession,
    *,
    lane: int | None = None,
    agent_id: str | None = None,
    workflow: str | None = None,
    status: str | None = None,
    older_than_minutes: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ApprovalItem], int]:
    stmt = select(ApprovalItem).order_by(ApprovalItem.created_at.desc())
    if status:
        stmt = stmt.where(ApprovalItem.status == status)
    else:
        stmt = stmt.where(ApprovalItem.status == ApprovalStatus.PENDING.value)
    if lane is not None:
        stmt = stmt.where(ApprovalItem.lane == lane)
    if agent_id:
        stmt = stmt.where(ApprovalItem.agent_id == agent_id)
    if workflow:
        stmt = stmt.where(ApprovalItem.workflow == workflow)
    if older_than_minutes:
        cutoff = _utcnow() - timedelta(minutes=older_than_minutes)
        stmt = stmt.where(ApprovalItem.created_at < cutoff)

    # cheap count
    count_res = await session.execute(stmt)
    total = len(count_res.scalars().all())

    page = await session.execute(stmt.offset(offset).limit(limit))
    return list(page.scalars().all()), total
