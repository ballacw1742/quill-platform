"""Approval Queue business logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import (
    AGENT_FLEET,
    OWNER_ONLY_WORKFLOWS,
    ApprovalStatus,
    AuthMethod,
    Decision,
    ExecutionResult,
    Lane,
    Priority,
    TrustTier,
    UserRole,
)
from app.models import AgentRegistration, ApprovalItem, ApprovalRecord, User
from app.services import agentcloud_actions
from app.services import lane_policy
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


def is_owner_only_workflow(workflow: str | None) -> bool:
    """ADK_AGENTS_DESIGN.md §4 — workflow-assignment (and any future
    live-workflow-mutating) approvals are owner-only and never auto-execute."""
    return workflow in OWNER_ONLY_WORKFLOWS


def owner_only_decide_allowed(workflow: str | None, role: str) -> bool:
    """True iff `role` may DECIDE an approval of this workflow. For owner-only
    workflows, only role=owner qualifies; all other workflows defer to the
    normal required_approvers authority check."""
    if is_owner_only_workflow(workflow):
        return (role or "").lower() == UserRole.OWNER.value
    return True


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
# Belt #2 — authoritative agent-cloud lane floor
# ---------------------------------------------------------------------------
async def _agentcloud_lane_floor(
    session: AsyncSession, *, payload: dict[str, Any], proposed_lane: int
) -> tuple[int, dict[str, Any]]:
    """Re-derive the lane for an agent-cloud proposal from the CANONICAL tier.

    Returns ``(final_lane, audit)``. The final lane is the STRICTEST of the
    lane agent-cloud proposed and the lane our own policy computes from the
    canonical ``AgentRegistration.trust_tier``. So agent-cloud can never make a
    write LESS strict than the api-side policy allows; a proposed Lane 1 on a
    money/contract/irreversible action is floored back to Lane 2/3 here.
    """
    pl = payload.get("payload") or {}
    proposed = pl.get("proposed_action") if isinstance(pl, dict) else None
    if not isinstance(proposed, dict):
        # Malformed — cannot risk-assess; force single-approver (never auto).
        floored = max(proposed_lane, Lane.SINGLE.value)
        return floored, {
            "belt": 2,
            "reason": "missing_proposed_action",
            "proposed_lane": proposed_lane,
            "final_lane": floored,
        }
    action = str(proposed.get("action") or "")
    args = proposed.get("args") if isinstance(proposed.get("args"), dict) else {}

    # Canonical trust tier: AgentRegistration keyed by the proposal's agent_id
    # ("agentcloud:{tenant}/{agent}"). Unknown/absent → strictest (never auto).
    agent_id = payload.get("agent_id") or ""
    trust_tier = TrustTier.TIER_0.value
    reg = await session.get(AgentRegistration, agent_id)
    if reg is not None and reg.trust_tier:
        trust_tier = reg.trust_tier

    decision = lane_policy.decide_lane(
        trust_tier=trust_tier, action=action, args=args
    )
    # STRICTEST wins: api policy floor vs. whatever agent-cloud proposed.
    final_lane = max(int(decision.lane), int(proposed_lane))
    audit = {
        "belt": 2,
        "canonical_trust_tier": trust_tier,
        "agent_id": agent_id,
        "proposed_lane": proposed_lane,
        "api_policy_lane": decision.lane,
        "final_lane": final_lane,
        "risk_flags": list(decision.risk_flags),
        "reasons": list(decision.reasons),
    }
    return final_lane, audit


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

    # ---- Belt #2: authoritative risk-graded lane for agent-cloud writes ----
    # Never trust the lane agent-cloud sent. Re-derive the lane floor from the
    # CANONICAL AgentRegistration.trust_tier + the proposed action's risk class
    # (shared lane-decision contract). If agent-cloud (buggy/compromised)
    # marked a money/contract/irreversible write as Lane 1, we floor it here.
    # This is Charles's HITL guarantee — do not weaken it.
    lane_audit: dict[str, Any] | None = None
    workflow = payload.get("workflow") or ""
    if agentcloud_actions.is_agentcloud_workflow(workflow):
        lane, lane_audit = await _agentcloud_lane_floor(
            session, payload=payload, proposed_lane=lane
        )

    # ADK_AGENTS_DESIGN.md §4: workflow-assignment items can NEVER auto-execute
    # (no Lane 1) and are always owner-only. Applied AFTER the belt-#2 floor so
    # owner-only always resolves toward the stricter outcome — a caller can
    # never request auto-execution of a live-workflow change.
    _owner_only = workflow in OWNER_ONLY_WORKFLOWS
    if _owner_only:
        if lane == Lane.AUTO.value:
            lane = Lane.DUAL.value
        payload = {**payload, "required_approvers": [UserRole.OWNER.value]}

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
            **({"lane_decision": lane_audit} if lane_audit else {}),
        },
    )
    item.audit_hash = entry.hash
    item.prev_audit_hash = entry.prev_hash
    
    # Lane 1 (auto) executes immediately, no human signature required.
    if item.lane == Lane.AUTO.value:
        await execute_approval(session, item.id, actor=actor)
        await session.refresh(item)

    await session.commit()
    # Sprint 5.5 (G7) — additive fields so push consumers (Telegram bot's
    # notifier.classify_event) can render lane/workflow/priority without a
    # follow-up fetch. Existing consumers only read type/id/status.
    await broadcaster.publish({
        "type": "approval.created",
        "id": item.id,
        "status": item.status,
        "lane": item.lane,
        "workflow": item.workflow,
        "priority": item.priority,
        "agent_id": item.agent_id,
        "payload": {
            "safety_critical": bool((item.payload or {}).get("safety_critical")),
            "critical_path": bool((item.payload or {}).get("critical_path")),
        },
    })
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

    # ADK_AGENTS_DESIGN.md §4 governance: workflow-assignment approvals are
    # OWNER-ONLY — only role=owner may decide (approve OR reject), regardless
    # of any agent trust tier or required_approvers list. This is the core
    # safety invariant: a non-owner can never change a live workflow.
    if not owner_only_decide_allowed(item.workflow, approver.role):
        raise PermissionError(
            f"workflow {item.workflow!r} is owner-only; role "
            f"{approver.role!r} cannot decide it"
        )

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

    if item.status == ApprovalStatus.REJECTED.value:
        await agentcloud_actions.notify_agentcloud_resolution(item)

    if item.status == ApprovalStatus.APPROVED.value:
        await execute_approval(session, item.id, actor=approver.id)
        await session.refresh(item)

    return item


# ---------------------------------------------------------------------------
# Execute (Sprint 1 stub + Phase D.1 publish hook)
# ---------------------------------------------------------------------------
# Phase G.1: Estimates artifacts also publish to Documents on approval.
# We extend the publish-artifact set rather than maintain a parallel one
# so any new estimate-flavor artifact gets the same lifecycle treatment.
_ESTIMATE_PUBLISH_WORKFLOWS: frozenset[str] = frozenset({
    "aace_classification.publish",
    "cost_schedule_package.publish",
})

# Sprint Contracts.1: contract extraction workflow
_CONTRACT_PUBLISH_WORKFLOWS: frozenset[str] = frozenset({
    "contract_extraction.publish",
})

# Sprint Contracts.2: contract review workflow
_CONTRACT_REVIEW_WORKFLOWS: frozenset[str] = frozenset({
    "contract_review.publish",
})

# Sprint Contracts.3: contract draft workflow
_CONTRACT_DRAFT_WORKFLOWS: frozenset[str] = frozenset({
    "contract_draft.publish",
})

# Sprint 2 (pipeline seams): site → project advance workflow.
# Execute-on-approve: the Project row is only created when a human approves.
SITE_ADVANCE_WORKFLOW = "site_advance.create_project"
_SITE_ADVANCE_WORKFLOWS: frozenset[str] = frozenset({SITE_ADVANCE_WORKFLOW})


def _is_publish_artifact(item: ApprovalItem) -> bool:
    """True if this approval should produce a Document on execute.

    Match on either:
      - workflow ID in the publish-artifact set, or
      - payload.proposed_action.kind == 'publish_artifact'.
    """
    # Lazy import to avoid a service<->service circular at module load.
    from app.services.documents import ARTIFACT_PUBLISH_WORKFLOWS, PUBLISH_ACTION_KIND

    wf = item.workflow or ""
    if wf in ARTIFACT_PUBLISH_WORKFLOWS or wf in _ESTIMATE_PUBLISH_WORKFLOWS:
        return True
    # Sprint Contracts.3: contract drafts also publish a Document on approval
    if wf in _CONTRACT_DRAFT_WORKFLOWS:
        return True
    # Sprint 4 fix: contract reviews were always *documented* as published
    # Documents (see contracts.list_reviews / GET /{upload_id}/reviews), but
    # this predicate never included the workflow, so no Document was ever
    # created and the reviews list stayed permanently empty.
    if wf in _CONTRACT_REVIEW_WORKFLOWS:
        return True
    payload = item.payload or {}
    proposed = payload.get("proposed_action") if isinstance(payload, dict) else None
    if isinstance(proposed, dict) and proposed.get("kind") == PUBLISH_ACTION_KIND:
        return True
    return False


def _extract_estimate_artifact_kind(item: ApprovalItem) -> str | None:
    """Return 'aace_classification' or 'cost_schedule_package' if this
    approval carries an estimate-flavor artifact, otherwise None."""
    payload = item.payload or {}
    artifact = payload.get("artifact") if isinstance(payload, dict) else None
    if isinstance(artifact, dict):
        at = artifact.get("artifact_type")
        if at in ("aace_classification", "cost_schedule_package"):
            return at
    return None


def _extract_contract_upload_id(item: ApprovalItem) -> str | None:
    """Pull upload_id out of a contract-extraction approval payload.

    The upload_id is placed in:
      payload.contract_upload_id, or
      payload.context.contract_upload_id
    """
    payload = item.payload or {}
    if not isinstance(payload, dict):
        return None
    if "contract_upload_id" in payload:
        return str(payload["contract_upload_id"])
    ctx = payload.get("context")
    if isinstance(ctx, dict) and "contract_upload_id" in ctx:
        return str(ctx["contract_upload_id"])
    return None


def _extract_estimate_upload_id(item: ApprovalItem) -> str | None:
    """Pull upload_id out of an estimate-flavor approval payload.

    The upload_id is conventionally placed in:
      payload.estimate_upload_id, or
      payload.context.estimate_upload_id, or
      payload.artifact.metadata.upload_id
    Whichever the agent / runtime sets first.
    """
    payload = item.payload or {}
    if not isinstance(payload, dict):
        return None
    if "estimate_upload_id" in payload:
        return str(payload["estimate_upload_id"])
    ctx = payload.get("context")
    if isinstance(ctx, dict) and "estimate_upload_id" in ctx:
        return str(ctx["estimate_upload_id"])
    artifact = payload.get("artifact")
    if isinstance(artifact, dict):
        meta = artifact.get("metadata")
        if isinstance(meta, dict) and "upload_id" in meta:
            return str(meta["upload_id"])
    return None


async def execute_approval(
    session: AsyncSession, approval_id: str, *, actor: str
) -> ApprovalItem:
    """Mark an approval executed. Phase D.1 dispatches publish_artifact items
    through the Documents service before sealing the audit chain.

    Idempotent.
    """
    item = await session.get(ApprovalItem, approval_id)
    if item is None:
        raise LookupError(f"approval {approval_id} not found")
    if item.status == ApprovalStatus.EXECUTED.value:
        return item
    if item.status not in (ApprovalStatus.APPROVED.value, ApprovalStatus.PENDING.value):
        raise ValueError(f"cannot execute from status={item.status}")

    document_id: str | None = None
    estimate_kind = _extract_estimate_artifact_kind(item)
    estimate_upload_id = _extract_estimate_upload_id(item) if estimate_kind else None

    # ---- Phase D.1: artifact publication path ----
    is_contract_extraction = item.workflow in _CONTRACT_PUBLISH_WORKFLOWS
    is_contract_review = item.workflow in _CONTRACT_REVIEW_WORKFLOWS
    is_contract_draft = item.workflow in _CONTRACT_DRAFT_WORKFLOWS
    contract_upload_id = (
        _extract_contract_upload_id(item)
        if (is_contract_extraction or is_contract_review or is_contract_draft)
        else None
    )

    # ---- Sprint A6: agent-cloud proposed writes (agent-cloud/APPROVALS.md) ----
    agentcloud_ref: str | None = None
    if agentcloud_actions.is_agentcloud_workflow(item.workflow):
        try:
            agentcloud_ref = await agentcloud_actions.execute_agentcloud_action(
                session, item, actor=actor
            )
        except Exception as exc:  # noqa: BLE001 — validation/lookup/db errors
            item.status = ApprovalStatus.EXECUTION_FAILED.value
            item.executed_at = _utcnow()
            item.execution_result = ExecutionResult.FAILED.value
            entry = await audit_svc.record_event(
                session,
                event_type="approval.execution_failed",
                actor=actor,
                approval_item_id=item.id,
                payload={"error": str(exc), "workflow": item.workflow},
            )
            item.prev_audit_hash = item.audit_hash
            item.audit_hash = entry.hash
            await session.commit()
            await broadcaster.publish(
                {"type": "approval.execution_failed", "id": item.id, "status": item.status}
            )
            await agentcloud_actions.notify_agentcloud_resolution(item, error=str(exc))
            raise

    # ---- Sprint 2: site → project advance path ----
    project_id: str | None = None
    if item.workflow in _SITE_ADVANCE_WORKFLOWS:
        from sqlalchemy import select as _select

        from app.models_projects import Project

        payload = item.payload or {}
        proj_fields = payload.get("project") or {}
        adv_site_id = proj_fields.get("site_id") or payload.get("site_id")
        try:
            existing_proj = None
            if adv_site_id:
                res = await session.execute(
                    _select(Project).where(Project.site_id == str(adv_site_id))
                )
                existing_proj = res.scalars().first()
            if existing_proj is not None:
                # Idempotent: a project for this site already exists.
                project_id = existing_proj.id
            else:
                if not proj_fields.get("name"):
                    raise ValueError("site_advance payload missing project.name")
                proj = Project(
                    user_id=str(payload.get("requested_by") or actor),
                    name=str(proj_fields["name"])[:255],
                    address=proj_fields.get("address"),
                    site_id=str(adv_site_id) if adv_site_id else None,
                    site_score=proj_fields.get("site_score"),
                    site_verdict=proj_fields.get("site_verdict"),
                    workload_type=proj_fields.get("workload_type"),
                    phase=proj_fields.get("phase") or "site_control",
                    status=proj_fields.get("status") or "active",
                    notes=proj_fields.get("notes"),
                )
                session.add(proj)
                await session.flush()
                project_id = proj.id
        except Exception as exc:  # noqa: BLE001
            item.status = ApprovalStatus.EXECUTION_FAILED.value
            item.executed_at = _utcnow()
            item.execution_result = ExecutionResult.FAILED.value
            entry = await audit_svc.record_event_with_mirror(
                session,
                event_type="approval.execution_failed",
                actor=actor,
                approval_item_id=item.id,
                payload={"error": str(exc), "workflow": item.workflow},
            )
            item.prev_audit_hash = item.audit_hash
            item.audit_hash = entry.hash
            await session.commit()
            await broadcaster.publish(
                {"type": "approval.execution_failed", "id": item.id, "status": item.status}
            )
            raise

    if _is_publish_artifact(item):
        from app.services.documents import service as docs_service

        try:
            doc = await docs_service.create_from_approval(session, item, actor=actor)
            document_id = doc.id
        except Exception as exc:  # noqa: BLE001
            # We deliberately mark execution_failed rather than burying the
            # exception: the audit chain should reflect that we tried and
            # couldn't, so an operator can re-run after fixing the cause.
            item.status = ApprovalStatus.EXECUTION_FAILED.value
            item.executed_at = _utcnow()
            item.execution_result = ExecutionResult.FAILED.value
            entry = await audit_svc.record_event(
                session,
                event_type="approval.execution_failed",
                actor=actor,
                approval_item_id=item.id,
                payload={"error": str(exc), "workflow": item.workflow},
            )
            item.prev_audit_hash = item.audit_hash
            item.audit_hash = entry.hash
            await session.commit()
            await broadcaster.publish(
                {"type": "approval.execution_failed", "id": item.id, "status": item.status}
            )
            raise

    item.status = ApprovalStatus.EXECUTED.value
    item.executed_at = _utcnow()
    # ---- Phase G.1: estimate lifecycle hook ----
    # If this approval published an estimate artifact, stamp the matching
    # Estimate row so /v1/estimates/{upload_id}/status reflects it. Both
    # the classification and the package paths are wired here.
    if document_id is not None and estimate_kind is not None and estimate_upload_id is not None:
        from app.services.estimates import service as est_service

        try:
            payload_artifact = (item.payload or {}).get("artifact") or {}
            artifact_id = str(payload_artifact.get("id") or document_id)
            if estimate_kind == "aace_classification":
                await est_service.on_classification_approved(
                    session,
                    upload_id=estimate_upload_id,
                    artifact_id=artifact_id,
                    actor=actor,
                )
            elif estimate_kind == "cost_schedule_package":
                await est_service.on_package_approved(
                    session,
                    upload_id=estimate_upload_id,
                    artifact_id=artifact_id,
                    actor=actor,
                )
        except Exception as exc:  # noqa: BLE001
            # Estimate stamping is best-effort.
            import logging

            logging.getLogger("quill.approvals").warning(
                "approvals.estimate_hook_failed kind=%s upload_id=%s err=%s",
                estimate_kind, estimate_upload_id, exc,
            )

    # Sprint Contracts.1: stamp Contract row when a contract_extraction is approved.
    if is_contract_extraction and contract_upload_id is not None:
        from app.services.contracts import service as contracts_service

        try:
            payload_artifact = (item.payload or {}).get("artifact") or {}
            artifact_id = str(payload_artifact.get("id") or document_id or item.id)
            await contracts_service.on_extraction_approved(
                session,
                upload_id=contract_upload_id,
                artifact_id=artifact_id,
                actor=actor,
                fields=payload_artifact if isinstance(payload_artifact, dict) else None,
            )
        except Exception as exc:  # noqa: BLE001
            import logging

            logging.getLogger("quill.approvals").warning(
                "approvals.contract_hook_failed upload_id=%s err=%s",
                contract_upload_id, exc,
            )

    # Sprint Contracts.2: stamp Contract.review_artifact_id when a contract_review is approved.
    if is_contract_review and contract_upload_id is not None:
        from app.services.contracts import service as contracts_service

        try:
            payload_artifact = (item.payload or {}).get("artifact") or {}
            artifact_id = str(payload_artifact.get("id") or document_id or item.id)
            await contracts_service.on_review_approved(
                session,
                upload_id=contract_upload_id,
                artifact_id=artifact_id,
                actor=actor,
            )
        except Exception as exc:  # noqa: BLE001
            import logging

            logging.getLogger("quill.approvals").warning(
                "approvals.contract_review_hook_failed upload_id=%s err=%s",
                contract_upload_id, exc,
            )

    # Sprint Contracts.3: stamp Contract.draft_artifact_id when a contract_draft is approved.
    if is_contract_draft and contract_upload_id is not None:
        from app.services.contracts import service as contracts_service

        try:
            payload_artifact = (item.payload or {}).get("artifact") or {}
            artifact_id = str(payload_artifact.get("id") or document_id or item.id)
            await contracts_service.on_draft_approved(
                session,
                upload_id=contract_upload_id,
                artifact_id=artifact_id,
                actor=actor,
            )
        except Exception as exc:  # noqa: BLE001
            import logging

            logging.getLogger("quill.approvals").warning(
                "approvals.contract_draft_hook_failed upload_id=%s err=%s",
                contract_upload_id, exc,
            )

    if document_id is not None:
        item.execution_result = ExecutionResult.SUCCESS.value
        item.external_ref = f"document:{document_id}"
    elif project_id is not None:
        item.execution_result = ExecutionResult.SUCCESS.value
        item.external_ref = f"project:{project_id}"
    elif agentcloud_ref is not None:
        item.execution_result = ExecutionResult.SUCCESS.value
        item.external_ref = agentcloud_ref
    else:
        # Non-publish workflows still flow through the Sprint 1 stub.
        item.execution_result = ExecutionResult.DRY_RUN.value
        item.external_ref = f"sprint1-stub:{item.id}"

    audit_payload: dict[str, Any] = {
        "execution_result": item.execution_result,
        "external_ref": item.external_ref,
        "target_system": item.target_system,
    }
    if document_id is not None:
        audit_payload["document_id"] = document_id
    if agentcloud_ref is not None:
        audit_payload["agentcloud_workflow"] = item.workflow
    if project_id is not None:
        audit_payload["project_id"] = project_id
        audit_payload["site_id"] = (item.payload or {}).get("site_id")

    entry = await audit_svc.record_event(
        session,
        event_type="approval.executed",
        actor=actor,
        approval_item_id=item.id,
        payload=audit_payload,
    )
    item.prev_audit_hash = item.audit_hash
    item.audit_hash = entry.hash

    await session.commit()
    await broadcaster.publish(
        {"type": "approval.executed", "id": item.id, "status": item.status}
    )
    await agentcloud_actions.notify_agentcloud_resolution(item)
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
    await agentcloud_actions.notify_agentcloud_resolution(item)
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
