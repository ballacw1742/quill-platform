"""Quill write tool suite (A6) — proposal-only, approval-gated.

None of these tools mutate Quill. Each validates its args and files an
approval item in the Quill /queue (workflow `agentcloud.<action>`) plus an
`agentcloud_proposals` row, then tells the model the write is *pending
human approval* (contract: agent-cloud/APPROVALS.md). Execution happens
api-side in the approvals executor only after a human approves.

Exposure: registry-present but NOT on any seed agent's allow-list — an
operator must add these names to the agent definition's tools JSONB.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app import approvals as approvals_mod
from app.tools.base import Tool

log = logging.getLogger("agentcloud.tools.quill_writes")

_PENDING_NOTE = (
    " This is a WRITE: it does not happen immediately — it is queued for "
    "human approval in Quill and you will be woken in this session when it "
    "is approved, declined, or expires."
)


def _handler(tool_name: str, action: str):
    async def handle(args: dict[str, Any]) -> str:
        args = dict(args or {})
        reasoning = args.pop("reasoning", None)
        if reasoning is not None and not isinstance(reasoning, str):
            reasoning = str(reasoning)
        try:
            result = await approvals_mod.create_proposal(
                tool_name=tool_name,
                action=action,
                args=args,
                reasoning=reasoning,
            )
        except approvals_mod.ProposalValidationError as exc:
            return json.dumps({"error": f"invalid args: {exc}"})
        except Exception as exc:  # noqa: BLE001 — queueing failure → model
            log.warning("proposal queueing failed (%s): %s", tool_name, exc)
            return json.dumps({"error": f"could not queue approval: {exc}"})
        return json.dumps(result, default=str)

    return handle


_REASONING_PROP = {
    "reasoning": {
        "type": "string",
        "description": "Short human-readable justification shown to the approver.",
    }
}

quill_project_update = Tool(
    name="quill_project_update",
    description=(
        "Propose a Quill project update (advance to the next phase, or set "
        "phase/status/notes). Requires human approval before anything changes."
        + _PENDING_NOTE
    ),
    handler=_handler("quill_project_update", "project_update"),
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "string", "description": "Quill project id."},
            "advance_phase": {
                "type": "boolean",
                "description": "true = advance to the next phase in order.",
            },
            "phase": {
                "type": "string",
                "enum": list(approvals_mod.VALID_PHASES),
                "description": "Set an explicit phase (mutually exclusive with advance_phase).",
            },
            "status": {
                "type": "string",
                "enum": list(approvals_mod.VALID_PROJECT_STATUSES),
            },
            "notes": {"type": "string", "description": "Replace project notes."},
            **_REASONING_PROP,
        },
        "required": ["project_id"],
    },
)

quill_project_log_note = Tool(
    name="quill_project_log_note",
    description=(
        "Propose adding a construction-log entry (note/issue/progress/"
        "weather/safety) to a Quill project." + _PENDING_NOTE
    ),
    handler=_handler("quill_project_log_note", "project_log_note"),
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "entry_type": {
                "type": "string",
                "enum": list(approvals_mod.VALID_ENTRY_TYPES),
            },
            "text": {"type": "string", "description": "Log entry text."},
            **_REASONING_PROP,
        },
        "required": ["project_id", "entry_type", "text"],
    },
)

quill_project_milestone_create = Tool(
    name="quill_project_milestone_create",
    description=(
        "Propose creating a milestone (task with optional due date) on a "
        "Quill project." + _PENDING_NOTE
    ),
    handler=_handler("quill_project_milestone_create", "project_milestone_create"),
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "name": {"type": "string", "description": "Milestone name."},
            "description": {"type": "string"},
            "due_date": {"type": "string", "description": "YYYY-MM-DD."},
            **_REASONING_PROP,
        },
        "required": ["project_id", "name"],
    },
)

quill_deal_update = Tool(
    name="quill_deal_update",
    description=(
        "Propose updating a Quill sales deal (stage, value, probability, "
        "expected close, notes, lost reason)." + _PENDING_NOTE
    ),
    handler=_handler("quill_deal_update", "deal_update"),
    input_schema={
        "type": "object",
        "properties": {
            "deal_id": {"type": "string"},
            "stage": {
                "type": "string",
                "enum": list(approvals_mod.VALID_DEAL_STAGES),
            },
            "value_usd": {"type": "number", "minimum": 0},
            "probability_pct": {"type": "number", "minimum": 0, "maximum": 100},
            "expected_close": {"type": "string", "description": "YYYY-MM-DD."},
            "notes": {"type": "string"},
            "lost_reason": {"type": "string"},
            **_REASONING_PROP,
        },
        "required": ["deal_id"],
    },
)

quill_request_update = Tool(
    name="quill_request_update",
    description=(
        "Propose marking a Quill request complete or failed, with an "
        "optional response for the requester." + _PENDING_NOTE
    ),
    handler=_handler("quill_request_update", "request_update"),
    input_schema={
        "type": "object",
        "properties": {
            "request_id": {"type": "string"},
            "status": {
                "type": "string",
                "enum": list(approvals_mod.VALID_REQUEST_STATUSES),
            },
            "response": {"type": "string"},
            **_REASONING_PROP,
        },
        "required": ["request_id", "status"],
    },
)

QUILL_WRITE_TOOLS = [
    quill_project_update,
    quill_project_log_note,
    quill_project_milestone_create,
    quill_deal_update,
    quill_request_update,
]

QUILL_WRITE_TOOL_NAMES = [t.name for t in QUILL_WRITE_TOOLS]


# --- Email send (approval-gated write, §9 Wave 2, MIGRATION.md §3.3) --------

async def _email_send_handler(args: dict[str, Any]) -> str:
    """Custom handler for quill_email_send — validates, queues proposal,
    and emits email.send_queued on success."""
    args = dict(args or {})
    reasoning = args.pop("reasoning", None)
    if reasoning is not None and not isinstance(reasoning, str):
        reasoning = str(reasoning)
    try:
        result = await approvals_mod.create_proposal(
            tool_name="quill_email_send",
            action="email_send",
            args=args,
            reasoning=reasoning,
        )
    except approvals_mod.ProposalValidationError as exc:
        return json.dumps({"error": f"invalid args: {exc}"})
    except Exception as exc:  # noqa: BLE001 — queueing failure → model
        log.warning("email proposal queueing failed: %s", exc)
        return json.dumps({"error": f"could not queue email approval: {exc}"})

    # Best-effort: emit email.send_queued event so consumers can react.
    from app import events as events_mod  # noqa: PLC0415 — avoid circular at module load
    from app.logging_setup import agent_id_var, session_id_var, tenant_id_var  # noqa: PLC0415

    tenant_id = tenant_id_var.get()
    if tenant_id:
        try:
            ev = events_mod.make_event(
                tenant_id=tenant_id,
                agent_id=agent_id_var.get() or "",
                session_id=session_id_var.get(),
                type="email.send_queued",
                payload={
                    "proposal_id": result.get("proposal_id"),
                    "to": args.get("to"),
                    "subject": args.get("subject"),
                },
            )
            import asyncio  # noqa: PLC0415
            asyncio.ensure_future(events_mod.emit([ev]))
        except Exception:  # noqa: BLE001 — best-effort; never fail the tool call
            pass

    return json.dumps(result, default=str)


quill_email_send = Tool(
    name="quill_email_send",
    description=(
        "Propose sending an email to one or more recipients. Requires human "
        "approval before anything is sent — the email is NEVER delivered "
        "automatically. Queued for approval in the Quill queue."
        + _PENDING_NOTE
    ),
    handler=_email_send_handler,
    input_schema={
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "Recipient email address.",
            },
            "subject": {
                "type": "string",
                "description": "Email subject (max 200 chars).",
            },
            "body": {
                "type": "string",
                "description": "Plain-text email body (max 10 000 chars).",
            },
            "cc": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional CC recipients (email addresses).",
            },
            **_REASONING_PROP,
        },
        "required": ["to", "subject", "body"],
    },
)

# Separate list so agents.py can expose it under its own catalog group.
EMAIL_WRITE_TOOLS = [quill_email_send]
EMAIL_WRITE_TOOL_NAMES = [t.name for t in EMAIL_WRITE_TOOLS]
