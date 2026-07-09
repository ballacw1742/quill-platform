"""Executor for agent-cloud proposed writes (workflow `agentcloud.*`).

Contract: agent-cloud/APPROVALS.md. Called from
`app.services.approvals.execute_approval` on human approval — the same
execute-on-approve seam as `site_advance.create_project`. Args are
re-validated here (belt #2; agent-cloud validated at queue time) and any
validation/lookup error raises `AgentCloudActionError`, which the caller
turns into EXECUTION_FAILED + an `approval.execution_failed` audit event.

Also home to the best-effort resolution notify: on any terminal transition
of an `agentcloud.*` approval, the api POSTs to the agent-cloud
`/v1/internal/approvals/notify` endpoint (shared secret; failure is logged
and swallowed — the agent-cloud reconcile sweep closes the gap).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.contracts import write_vocab as _write_vocab
from app.models_pipeline import Account, Deal
from app.models_projects import (
    Project,
    ProjectLogEntry,
    ProjectMilestone,
)
from app.models_requests import RequestRecord

log = logging.getLogger("quill.agentcloud_actions")

WORKFLOW_PREFIX = "agentcloud."

# Belt #2 re-validation reads the SAME shared, generated contract that
# agent-cloud validates against at queue time (Phase 0, GAP §3). The contract
# is generated from the api canonical ORM models, so these stay authoritative.
_VOCAB = _write_vocab()
VALID_PHASES = _VOCAB["project_phases"]
VALID_STATUSES = _VOCAB["project_statuses"]
VALID_ENTRY_TYPES = _VOCAB["log_entry_types"]
VALID_DEAL_STAGES = _VOCAB["deal_stages"]
VALID_REQUEST_ACTION_STATUSES = _VOCAB["request_action_statuses"]

# Phase order for advance_phase (shared contract; source = VALID_PHASES order).
PHASE_ORDER = list(_VOCAB["phase_order"])

_ACTIONS = (
    "project_update",
    "project_log_note",
    "project_milestone_create",
    "deal_update",
    "request_update",
)


class AgentCloudActionError(ValueError):
    """Invalid proposed_action / target not found / bad values."""


def is_agentcloud_workflow(workflow: str | None) -> bool:
    return bool(workflow) and workflow.startswith(WORKFLOW_PREFIX)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _parse_date(value: Any, key: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise AgentCloudActionError(f"{key} must be YYYY-MM-DD") from exc


def _proposed_action(item) -> dict[str, Any]:
    payload = item.payload or {}
    proposed = payload.get("proposed_action") if isinstance(payload, dict) else None
    if not isinstance(proposed, dict) or proposed.get("kind") != "agentcloud_write":
        raise AgentCloudActionError("payload.proposed_action missing or malformed")
    action = str(proposed.get("action") or "")
    if action not in _ACTIONS:
        raise AgentCloudActionError(f"unknown agentcloud action {action!r}")
    if item.workflow != WORKFLOW_PREFIX + action:
        raise AgentCloudActionError(
            f"workflow {item.workflow!r} does not match action {action!r}"
        )
    args = proposed.get("args")
    if not isinstance(args, dict):
        raise AgentCloudActionError("proposed_action.args must be an object")
    return proposed


async def execute_agentcloud_action(session: AsyncSession, item, *, actor: str) -> str:
    """Apply the approved write. Returns external_ref. Raises AgentCloudActionError."""
    proposed = _proposed_action(item)
    action: str = proposed["action"]
    args: dict[str, Any] = proposed["args"]

    if action == "project_update":
        project = await session.get(Project, str(args.get("project_id")))
        if project is None:
            raise AgentCloudActionError(f"project {args.get('project_id')!r} not found")
        # Validate everything BEFORE mutating (a raise after partial mutation
        # would otherwise be committed by the caller's failure bookkeeping).
        if args.get("phase") is not None and args["phase"] not in VALID_PHASES:
            raise AgentCloudActionError(f"phase must be one of {VALID_PHASES}")
        if args.get("status") is not None and args["status"] not in VALID_STATUSES:
            raise AgentCloudActionError(f"status must be one of {VALID_STATUSES}")
        if args.get("advance_phase"):
            try:
                idx = PHASE_ORDER.index(project.phase)
            except ValueError:
                idx = -1
            if idx >= len(PHASE_ORDER) - 1:
                raise AgentCloudActionError("project is already at the final phase")
            project.phase = PHASE_ORDER[idx + 1]
        elif args.get("phase") is not None:
            project.phase = args["phase"]
        if args.get("status") is not None:
            project.status = args["status"]
        if args.get("notes") is not None:
            project.notes = str(args["notes"])
        project.updated_at = _utcnow()
        await session.flush()
        return f"project:{project.id}"

    if action == "project_log_note":
        project = await session.get(Project, str(args.get("project_id")))
        if project is None:
            raise AgentCloudActionError(f"project {args.get('project_id')!r} not found")
        entry_type = str(args.get("entry_type") or "")
        text = str(args.get("text") or "").strip()
        if entry_type not in VALID_ENTRY_TYPES:
            raise AgentCloudActionError(f"entry_type must be one of {VALID_ENTRY_TYPES}")
        if not text:
            raise AgentCloudActionError("text is required")
        entry = ProjectLogEntry(
            project_id=project.id,
            user_id=str(project.user_id),
            entry_type=entry_type,
            text=text,
        )
        session.add(entry)
        await session.flush()
        return f"project_log:{entry.id}"

    if action == "project_milestone_create":
        project = await session.get(Project, str(args.get("project_id")))
        if project is None:
            raise AgentCloudActionError(f"project {args.get('project_id')!r} not found")
        name = str(args.get("name") or "").strip()
        if not name:
            raise AgentCloudActionError("name is required")
        milestone = ProjectMilestone(
            project_id=project.id,
            name=name[:255],
            description=(str(args["description"]) if args.get("description") else None),
            due_date=(_parse_date(args["due_date"], "due_date") if args.get("due_date") else None),
        )
        session.add(milestone)
        await session.flush()
        return f"milestone:{milestone.id}"

    if action == "deal_update":
        deal = await session.get(Deal, str(args.get("deal_id")))
        if deal is None:
            raise AgentCloudActionError(f"deal {args.get('deal_id')!r} not found")
        # Validate/parse everything BEFORE mutating (see project_update note).
        if args.get("stage") is not None and args["stage"] not in VALID_DEAL_STAGES:
            raise AgentCloudActionError(f"stage must be one of {VALID_DEAL_STAGES}")
        try:
            value_usd = float(args["value_usd"]) if args.get("value_usd") is not None else None
            probability = (
                int(round(float(args["probability_pct"])))
                if args.get("probability_pct") is not None
                else None
            )
        except (TypeError, ValueError) as exc:
            raise AgentCloudActionError("value_usd/probability_pct must be numbers") from exc
        expected_close = (
            _parse_date(args["expected_close"], "expected_close")
            if args.get("expected_close") is not None
            else None
        )
        if args.get("stage") is not None:
            if args["stage"] == "won":
                # Same side effect as the human PATCH route: prospect → customer.
                res = await session.execute(
                    select(Account).where(Account.id == deal.account_id)
                )
                account = res.scalars().first()
                if account is not None and account.type == "prospect":
                    account.type = "customer"
                    account.updated_at = _utcnow()
            deal.stage = args["stage"]
        if value_usd is not None:
            deal.value_usd = value_usd
        if probability is not None:
            deal.probability_pct = probability
        if expected_close is not None:
            deal.expected_close = expected_close
        if args.get("notes") is not None:
            deal.notes = str(args["notes"])
        if args.get("lost_reason") is not None:
            deal.lost_reason = str(args["lost_reason"])
        deal.updated_at = _utcnow()
        await session.flush()
        return f"deal:{deal.id}"

    if action == "request_update":
        record = await session.get(RequestRecord, str(args.get("request_id")))
        if record is None:
            raise AgentCloudActionError(f"request {args.get('request_id')!r} not found")
        status_val = str(args.get("status") or "")
        if status_val not in VALID_REQUEST_ACTION_STATUSES:
            raise AgentCloudActionError(
                f"status must be one of {VALID_REQUEST_ACTION_STATUSES}"
            )
        record.status = status_val
        if args.get("response") is not None:
            record.response = str(args["response"])
        record.updated_at = _utcnow()
        await session.flush()
        return f"request:{record.id}"

    raise AgentCloudActionError(f"unknown agentcloud action {action!r}")  # unreachable


# ---------------------------------------------------------------------------
# Resolution notify (api → agent-cloud, best-effort — APPROVALS.md §6)
# ---------------------------------------------------------------------------


async def notify_agentcloud_resolution(item, *, error: str | None = None) -> None:
    """POST the terminal state to agent-cloud. Never raises.

    Disabled when AGENTCLOUD_NOTIFY_SECRET is unset — the agent-cloud
    reconcile sweep still closes the loop by polling.
    """
    if not is_agentcloud_workflow(getattr(item, "workflow", None)):
        return
    settings = get_settings()
    secret = getattr(settings, "AGENTCLOUD_NOTIFY_SECRET", "")
    if not secret:
        return
    payload = (item.payload or {}) if isinstance(item.payload, dict) else {}
    proposed = payload.get("proposed_action") or {}
    body = {
        "approval_id": item.id,
        "workflow": item.workflow,
        "status": item.status,
        "tenant_id": str(proposed.get("tenant_id") or ""),
        "proposal_id": proposed.get("proposal_id"),
        "external_ref": getattr(item, "external_ref", None),
        "error": error,
    }
    if not body["tenant_id"]:
        log.warning("agentcloud notify: approval %s has no tenant_id — skipped", item.id)
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{settings.AGENTCLOUD_URL}/v1/internal/approvals/notify",
                json=body,
                headers={"X-Agent-Secret": secret},
            )
        if r.status_code != 200:
            log.warning(
                "agentcloud notify: %s → HTTP %s %s",
                item.id,
                r.status_code,
                r.text[:200],
            )
    except Exception as exc:  # noqa: BLE001 — best-effort by contract
        log.warning("agentcloud notify failed for %s: %s", item.id, exc)
