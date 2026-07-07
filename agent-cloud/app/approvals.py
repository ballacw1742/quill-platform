"""Agent-proposed Quill writes → HITL approval queue (A6, APPROVALS.md).

Nothing here mutates a Quill business object. A write tool validates its
args, POSTs an approval item to the Quill queue (X-Agent-Secret — the
endpoint that has always been agent-facing), records an
`agentcloud_proposals` row, and returns "pending approval" to the model.
Execution happens api-side inside the existing approvals executor when a
human approves; this module then *finalizes* the proposal via the notify
endpoint (push) or the scheduler reconcile sweep (pull, belt #2).

Finalization is race-safe by construction: the terminal transition is a
conditional UPDATE (WHERE status='pending'), so notify + reconcile can both
fire and exactly one wake message / approval.resolved event is produced.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import sqlalchemy as sa

from app import events as events_mod
from app.config import get_settings
from app.db import admin_session, tenant_session
from app.logging_setup import agent_id_var, session_id_var, tenant_id_var
from app.models import Message, Proposal, Session

log = logging.getLogger("agentcloud.approvals")

PROPOSAL_STATUSES = ("pending", "executed", "declined", "failed", "expired")

# Quill ApprovalStatus → proposal status (APPROVALS.md §7). Anything not in
# this map (pending/approved/suspended/escalated) is still open — no-op.
QUILL_STATUS_MAP = {
    "executed": "executed",
    "rejected": "declined",
    "execution_failed": "failed",
    "cancelled": "expired",
    "expired": "expired",
}


class ProposalValidationError(ValueError):
    """Tool args failed schema validation — nothing was queued."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Args validation (queue-time belt; api validates again at execute time)
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Mirrors of the api-side vocabularies (canonical: api/app/models_projects.py
# and api/app/routes/pipeline.py). Kept in sync by the A6 contract tests.
VALID_PHASES = (
    "site_control",
    "permitting",
    "design",
    "construction",
    "commissioning",
    "turnover",
)
VALID_PROJECT_STATUSES = ("active", "on_hold", "completed", "cancelled")
VALID_ENTRY_TYPES = ("note", "issue", "progress", "weather", "safety")
VALID_DEAL_STAGES = ("prospect", "qualified", "proposal", "negotiating", "won", "lost")
VALID_REQUEST_STATUSES = ("complete", "failed")


def _req_str(args: dict, key: str, max_len: int = 200) -> str:
    val = args.get(key)
    if not isinstance(val, str) or not val.strip():
        raise ProposalValidationError(f"{key!r} is required (non-empty string)")
    if len(val) > max_len:
        raise ProposalValidationError(f"{key!r} exceeds {max_len} chars")
    return val.strip()


def _opt_str(args: dict, key: str, max_len: int) -> str | None:
    val = args.get(key)
    if val is None:
        return None
    if not isinstance(val, str):
        raise ProposalValidationError(f"{key!r} must be a string")
    if len(val) > max_len:
        raise ProposalValidationError(f"{key!r} exceeds {max_len} chars")
    return val


def _opt_date(args: dict, key: str) -> str | None:
    val = args.get(key)
    if val is None:
        return None
    if not isinstance(val, str) or not _DATE_RE.match(val):
        raise ProposalValidationError(f"{key!r} must be a YYYY-MM-DD date string")
    return val


def _reject_unknown(args: dict, allowed: set[str]) -> None:
    unknown = set(args) - allowed
    if unknown:
        raise ProposalValidationError(f"unknown args: {sorted(unknown)}")


def validate_args(action: str, args: dict[str, Any]) -> dict[str, Any]:
    """Normalize + validate per APPROVALS.md §2. Raises ProposalValidationError."""
    if not isinstance(args, dict):
        raise ProposalValidationError("args must be an object")

    if action == "project_update":
        _reject_unknown(args, {"project_id", "advance_phase", "phase", "status", "notes"})
        out: dict[str, Any] = {"project_id": _req_str(args, "project_id")}
        if args.get("advance_phase") is not None:
            if args["advance_phase"] is not True:
                raise ProposalValidationError("advance_phase must be true when present")
            out["advance_phase"] = True
        phase = _opt_str(args, "phase", 50)
        if phase is not None:
            if phase not in VALID_PHASES:
                raise ProposalValidationError(f"phase must be one of {VALID_PHASES}")
            out["phase"] = phase
        status = _opt_str(args, "status", 50)
        if status is not None:
            if status not in VALID_PROJECT_STATUSES:
                raise ProposalValidationError(
                    f"status must be one of {VALID_PROJECT_STATUSES}"
                )
            out["status"] = status
        notes = _opt_str(args, "notes", 4000)
        if notes is not None:
            out["notes"] = notes
        if len(out) == 1:
            raise ProposalValidationError(
                "project_update needs at least one of advance_phase/phase/status/notes"
            )
        if out.get("advance_phase") and "phase" in out:
            raise ProposalValidationError("pass either advance_phase or phase, not both")
        return out

    if action == "project_log_note":
        _reject_unknown(args, {"project_id", "entry_type", "text"})
        entry_type = _req_str(args, "entry_type", 50)
        if entry_type not in VALID_ENTRY_TYPES:
            raise ProposalValidationError(
                f"entry_type must be one of {VALID_ENTRY_TYPES}"
            )
        return {
            "project_id": _req_str(args, "project_id"),
            "entry_type": entry_type,
            "text": _req_str(args, "text", 4000),
        }

    if action == "project_milestone_create":
        _reject_unknown(args, {"project_id", "name", "description", "due_date"})
        out = {
            "project_id": _req_str(args, "project_id"),
            "name": _req_str(args, "name", 200),
        }
        desc = _opt_str(args, "description", 2000)
        if desc is not None:
            out["description"] = desc
        due = _opt_date(args, "due_date")
        if due is not None:
            out["due_date"] = due
        return out

    if action == "deal_update":
        _reject_unknown(
            args,
            {
                "deal_id",
                "stage",
                "value_usd",
                "probability_pct",
                "expected_close",
                "notes",
                "lost_reason",
            },
        )
        out = {"deal_id": _req_str(args, "deal_id")}
        stage = _opt_str(args, "stage", 50)
        if stage is not None:
            if stage not in VALID_DEAL_STAGES:
                raise ProposalValidationError(f"stage must be one of {VALID_DEAL_STAGES}")
            out["stage"] = stage
        if args.get("value_usd") is not None:
            try:
                val = float(args["value_usd"])
            except (TypeError, ValueError) as exc:
                raise ProposalValidationError("value_usd must be a number") from exc
            if val < 0:
                raise ProposalValidationError("value_usd must be >= 0")
            out["value_usd"] = val
        if args.get("probability_pct") is not None:
            try:
                pct = float(args["probability_pct"])
            except (TypeError, ValueError) as exc:
                raise ProposalValidationError("probability_pct must be a number") from exc
            if not 0 <= pct <= 100:
                raise ProposalValidationError("probability_pct must be 0-100")
            out["probability_pct"] = pct
        close = _opt_date(args, "expected_close")
        if close is not None:
            out["expected_close"] = close
        notes = _opt_str(args, "notes", 4000)
        if notes is not None:
            out["notes"] = notes
        lost = _opt_str(args, "lost_reason", 1000)
        if lost is not None:
            out["lost_reason"] = lost
        if len(out) == 1:
            raise ProposalValidationError("deal_update needs at least one field to change")
        return out

    if action == "request_update":
        _reject_unknown(args, {"request_id", "status", "response"})
        status = _req_str(args, "status", 20)
        if status not in VALID_REQUEST_STATUSES:
            raise ProposalValidationError(
                f"status must be one of {VALID_REQUEST_STATUSES}"
            )
        out = {"request_id": _req_str(args, "request_id"), "status": status}
        resp = _opt_str(args, "response", 8000)
        if resp is not None:
            out["response"] = resp
        return out

    raise ProposalValidationError(f"unknown action {action!r}")


def idempotency_key(tenant_id: str, agent_id: str, tool_name: str, args: dict) -> str:
    canonical = json.dumps(args, sort_keys=True, default=str)
    digest = hashlib.sha256(
        f"{tenant_id}|{agent_id}|{tool_name}|{canonical}".encode()
    ).hexdigest()
    return f"sha256:{digest}"


# ---------------------------------------------------------------------------
# Create (tool → queue)
# ---------------------------------------------------------------------------

# api_call hints per action (documentation-grade; the executor is in-process)
_API_CALL = {
    "project_update": "PATCH /v1/projects/{project_id}",
    "project_log_note": "POST /v1/projects/{project_id}/log",
    "project_milestone_create": "POST /v1/projects/{project_id}/milestones",
    "deal_update": "PATCH /v1/deals/{deal_id}",
    "request_update": "PATCH /v1/requests/{request_id}",
}


async def _post_approval(payload: dict[str, Any]) -> dict[str, Any]:
    """POST /v1/approvals with the agent secret. Raises on any failure."""
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


async def create_proposal(
    *,
    tool_name: str,
    action: str,
    args: dict[str, Any],
    reasoning: str | None = None,
) -> dict[str, Any]:
    """Validate → queue in Quill → persist proposal → 'pending approval'.

    Tenant/agent/session come from the request contextvars (set in
    stream_turn before tools run, including the jobs path). Returns the
    dict the write tool JSON-serializes back to the model.
    """
    tenant_id = tenant_id_var.get()
    agent_id = agent_id_var.get() or ""
    session_id = session_id_var.get()
    if not tenant_id:
        return {"error": "no tenant context — write tools only run inside a turn"}

    clean = validate_args(action, args or {})  # ProposalValidationError → caller
    idem = idempotency_key(tenant_id, agent_id, tool_name, clean)

    # Queue-time idempotency: matching pending proposal ⇒ return it, no re-POST.
    async with tenant_session(tenant_id) as db:
        existing = (
            await db.execute(
                sa.select(Proposal).where(
                    Proposal.tenant_id == tenant_id,
                    Proposal.idempotency_key == idem,
                    Proposal.status == "pending",
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return {
                "status": "pending_approval",
                "proposal_id": str(existing.proposal_id),
                "quill_approval_id": existing.quill_approval_id,
                "note": "an identical proposal is already awaiting human approval",
            }

    proposal_id = uuid.uuid4()
    payload = {
        "agent_id": f"agentcloud:{tenant_id}/{agent_id}",
        "agent_version": "a6",
        "workflow": f"agentcloud.{action}",
        "lane": 2,  # always single-approver; never auto-execute (APPROVALS.md §3)
        "priority": "normal",
        "target_system": "none",
        "api_call": _API_CALL.get(action),
        "payload": {
            "proposed_action": {
                "kind": "agentcloud_write",
                "action": action,
                "args": clean,
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "session_id": session_id,
                "proposal_id": str(proposal_id),
                "idempotency_key": idem,
            }
        },
        "agent_reasoning": (reasoning or "")[:2000] or None,
    }
    quill = await _post_approval(payload)  # RuntimeError/httpx errors → caller
    quill_approval_id = str(quill.get("id"))

    ev = events_mod.make_event(
        tenant_id=tenant_id,
        agent_id=agent_id,
        session_id=session_id,
        type="approval.requested",
        payload={
            "proposal_id": str(proposal_id),
            "tool": tool_name,
            "action": action,
            "quill_approval_id": quill_approval_id,
            "args_preview": json.dumps(clean, default=str)[:300],
        },
    )
    async with tenant_session(tenant_id) as db:
        db.add(
            Proposal(
                proposal_id=proposal_id,
                tenant_id=tenant_id,
                agent_id=agent_id,
                session_id=uuid.UUID(session_id) if session_id else None,
                tool_name=tool_name,
                action=action,
                args=clean,
                idempotency_key=idem,
                quill_approval_id=quill_approval_id,
                status="pending",
            )
        )
        events_mod.record_events(db, [ev])
    await events_mod.emit([ev])
    log.info(
        "proposal queued",
        extra={
            "extra_fields": {
                "proposal_id": str(proposal_id),
                "action": action,
                "quill_approval_id": quill_approval_id,
            }
        },
    )
    return {
        "status": "pending_approval",
        "proposal_id": str(proposal_id),
        "quill_approval_id": quill_approval_id,
        "workflow": f"agentcloud.{action}",
        "note": (
            "queued for human approval in the Quill /queue — the write will "
            "only happen if a human approves; you'll get a system wake in "
            "this session when it resolves"
        ),
    }


# ---------------------------------------------------------------------------
# Finalize (notify + reconcile share this; idempotent under races)
# ---------------------------------------------------------------------------


def _wake_text(prop: Proposal, status: str, result: dict[str, Any]) -> str:
    head = f"[system wake] Approval for {prop.tool_name} ({prop.action}) "
    args_preview = json.dumps(prop.args, default=str)[:200]
    if status == "executed":
        ref = result.get("external_ref") or "n/a"
        return (
            head
            + f"was APPROVED and executed.\nArgs: {args_preview}\nResult: {ref}"
        )
    if status == "declined":
        return (
            head
            + "was DECLINED by the human reviewer. Do not retry the same "
            + f"write unless asked.\nArgs: {args_preview}"
        )
    if status == "failed":
        err = result.get("error") or "unknown error"
        return head + f"was approved but execution FAILED.\nError: {err}"
    return head + "expired or was cancelled without a decision."


async def finalize_proposal(
    *,
    tenant_id: str,
    quill_approval_id: str,
    status: str,
    external_ref: str | None = None,
    error: str | None = None,
    source: str = "notify",
) -> bool:
    """Terminal transition. Returns True iff this call did the transition.

    Conditional UPDATE (WHERE status='pending') makes it a no-op when the
    other path (notify vs reconcile) already finalized — exactly one wake
    message and one approval.resolved event per proposal.
    """
    if status not in ("executed", "declined", "failed", "expired"):
        raise ValueError(f"invalid terminal status {status!r}")
    result = {
        "status": status,
        "external_ref": external_ref,
        "error": error,
        "source": source,
    }
    async with tenant_session(tenant_id) as db:
        prop = (
            await db.execute(
                sa.select(Proposal).where(
                    Proposal.tenant_id == tenant_id,
                    Proposal.quill_approval_id == quill_approval_id,
                )
            )
        ).scalar_one_or_none()
        if prop is None:
            log.warning(
                "finalize: no proposal for quill approval %s (tenant %s)",
                quill_approval_id,
                tenant_id,
            )
            return False
        updated = (
            await db.execute(
                sa.update(Proposal)
                .where(
                    Proposal.proposal_id == prop.proposal_id,
                    Proposal.tenant_id == tenant_id,
                    Proposal.status == "pending",
                )
                .values(
                    status=status,
                    result=result,
                    updated_at=_utcnow(),
                    resolved_at=_utcnow(),
                )
            )
        ).rowcount
        if not updated:
            return False  # lost the race — other path finalized already
        ev = events_mod.make_event(
            tenant_id=tenant_id,
            agent_id=prop.agent_id,
            session_id=prop.session_id,
            type="approval.resolved",
            payload={
                "proposal_id": str(prop.proposal_id),
                "quill_approval_id": quill_approval_id,
                "status": status,
                "external_ref": external_ref,
                "error": error,
                "source": source,
            },
        )
        events_mod.record_events(db, [ev])
        if prop.session_id is not None:
            db.add(
                Message(
                    session_id=prop.session_id,
                    tenant_id=tenant_id,
                    role="user",
                    content=[{"type": "text", "text": _wake_text(prop, status, result)}],
                )
            )
            await db.execute(
                sa.update(Session)
                .where(
                    Session.session_id == prop.session_id,
                    Session.tenant_id == tenant_id,
                )
                .values(updated_at=_utcnow())
            )
    await events_mod.emit([ev])
    log.info(
        "proposal finalized",
        extra={
            "extra_fields": {
                "proposal_id": str(prop.proposal_id),
                "status": status,
                "source": source,
            }
        },
    )
    return True


# ---------------------------------------------------------------------------
# Reconcile sweep (belt #2 — runs on the A4 scheduler tick)
# ---------------------------------------------------------------------------


async def _get_quill_approval(approval_id: str) -> dict[str, Any] | None:
    s = get_settings()
    if not s.QUILL_AGENT_SECRET:
        return None
    try:
        async with httpx.AsyncClient(timeout=s.QUILL_TOOL_TIMEOUT_SECONDS) as client:
            r = await client.get(
                f"{s.QUILL_API_URL}/v1/approvals/{approval_id}",
                headers={"X-Agent-Secret": s.QUILL_AGENT_SECRET},
            )
    except httpx.HTTPError as exc:
        log.warning("reconcile: GET approval %s failed: %s", approval_id, exc)
        return None
    if r.status_code != 200:
        log.warning("reconcile: GET approval %s → %s", approval_id, r.status_code)
        return None
    try:
        return r.json()
    except ValueError:
        return None


async def reconcile_sweep(now: datetime | None = None) -> dict[str, int]:
    """Poll stale pending proposals against Quill; finalize any resolved.

    Never raises (same contract as the scheduler tick). Cross-tenant listing
    uses the admin RLS policy (maintenance path, same as schedule claiming);
    per-proposal finalization goes back through tenant sessions.
    """
    s = get_settings()
    now = now or _utcnow()
    cutoff = now - timedelta(seconds=s.APPROVALS_RECONCILE_AFTER_SECONDS)
    checked = 0
    resolved = 0
    try:
        async with admin_session() as db:
            rows = (
                await db.execute(
                    sa.select(
                        Proposal.tenant_id,
                        Proposal.quill_approval_id,
                    )
                    .where(
                        Proposal.status == "pending",
                        Proposal.created_at <= cutoff,
                        Proposal.quill_approval_id.is_not(None),
                    )
                    .order_by(Proposal.created_at)
                    .limit(s.APPROVALS_RECONCILE_MAX_PER_TICK)
                )
            ).all()
    except Exception:  # noqa: BLE001 — sweep must not break the tick
        log.exception("reconcile sweep: listing failed")
        return {"checked": 0, "resolved": 0}

    for tenant_id, quill_approval_id in rows:
        checked += 1
        try:
            item = await _get_quill_approval(quill_approval_id)
            if not item:
                continue
            mapped = QUILL_STATUS_MAP.get(str(item.get("status")))
            if mapped is None:
                continue  # still open queue-side
            error = None
            if mapped == "failed":
                error = "execution failed in Quill (see approval audit trail)"
            did = await finalize_proposal(
                tenant_id=tenant_id,
                quill_approval_id=quill_approval_id,
                status=mapped,
                external_ref=item.get("external_ref"),
                error=error,
                source="reconcile",
            )
            if did:
                resolved += 1
        except Exception:  # noqa: BLE001
            log.exception(
                "reconcile sweep: proposal for approval %s failed", quill_approval_id
            )
    if checked:
        log.info(
            "approvals reconcile sweep",
            extra={"extra_fields": {"checked": checked, "resolved": resolved}},
        )
    return {"checked": checked, "resolved": resolved}
