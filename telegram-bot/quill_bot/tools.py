"""Tool definitions for the conversational Telegram bot (Phase B).

Each tool has:
  - A name (str)
  - A description (str) shown to Claude
  - A JSON-Schema input schema (dict)
  - A Pydantic input model used to validate at execution time
  - An async executor function (chat_ctx, raw_input) -> result_dict

Tools are wrapped in ToolSpec records and registered in TOOL_REGISTRY.
Each tool wraps an existing ApiClient method or a small helper.

Hard rules (enforced by these wrappers):
  - No tool writes to a system of record. The bot never approves anything,
    never sends external comms, never modifies queue items.
  - Approval intents (`approve` / `reject` / `edit`) are realized via signed
    deep links — `generate_deep_link` returns a URL, nothing more.
  - `dispatch_agent` runs the runtime in *dry_run* mode only; whatever it
    produces is returned to the caller and shown to the user. The user must
    explicitly confirm before any non-dry-run dispatch happens at the
    handler layer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError

from quill_bot.api_client import QuillAPIClient, QuillAPIError
from quill_bot.config import BotConfig
from quill_bot.deeplink import make as make_deeplink

log = logging.getLogger("quill.bot.tools")


# ---------------------------------------------------------------------------
# Chat context — what an executor needs to do its job.
# ---------------------------------------------------------------------------
@dataclass
class ChatContext:
    api: QuillAPIClient
    config: BotConfig
    chat_id: int
    user_id: str | None = None  # filled in once the chat is paired


# ---------------------------------------------------------------------------
# Pydantic input models — used to validate raw_input from Claude.
# ---------------------------------------------------------------------------
class SearchApprovalsInput(BaseModel):
    query: str | None = None
    lane: int | None = Field(default=None, ge=1, le=3)
    status: str | None = None
    limit: int = Field(default=10, ge=1, le=50)


class GetApprovalInput(BaseModel):
    id: str = Field(min_length=1)


class GetAuditInput(BaseModel):
    approval_id: str | None = None
    since: str | None = None
    action_type: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class GetAgentStatusInput(BaseModel):
    agent_id: str | None = None


class GetHealthInput(BaseModel):
    pass


class DispatchAgentInput(BaseModel):
    agent_id: str = Field(min_length=1)
    input_payload: dict[str, Any]
    summary: str = Field(min_length=1)


class GenerateDeepLinkInput(BaseModel):
    approval_id: str = Field(min_length=1)
    intent: Literal["approve", "reject", "edit", "view"]
    reason: str | None = None


class CurrentTimeInput(BaseModel):
    pass


class WhoamiInput(BaseModel):
    pass


# ---------------------------------------------------------------------------
# ToolSpec — schema + executor.
# ---------------------------------------------------------------------------
ToolExecutor = Callable[[ChatContext, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    input_model: type[BaseModel]
    executor: ToolExecutor

    def to_anthropic(self) -> dict[str, Any]:
        """Convert to Anthropic tool-use schema."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


# ---------------------------------------------------------------------------
# Executors — Commit 3 will fill in real bodies. Each accepts the validated
# input dict and returns a JSON-serialisable dict.
# ---------------------------------------------------------------------------
async def _exec_search_approvals(
    ctx: ChatContext, raw: dict[str, Any]
) -> dict[str, Any]:
    args = SearchApprovalsInput.model_validate(raw)
    try:
        # The bot's existing list_pending only queries pending; we pass a wider
        # set of params via the lower-level _req when we need non-pending too.
        params: dict[str, Any] = {
            "limit": args.limit,
            "offset": 0,
        }
        if args.lane is not None:
            params["lane"] = args.lane
        params["status"] = args.status or "pending"
        # Use the existing client method if status==pending (gives bare list back),
        # otherwise hit the endpoint directly via _req.
        if params["status"] == "pending":
            items_raw = await ctx.api.list_pending(
                lane=args.lane, limit=args.limit, offset=0
            )
        else:
            resp = await ctx.api._req("GET", "/v1/approvals", params=params)
            # Endpoint returns {items, total, limit, offset}
            items_raw = resp.get("items", []) if isinstance(resp, dict) else resp
    except QuillAPIError as e:
        return {"error": f"API error {e.status}", "items": []}

    # The list endpoint may return either a bare list (existing client) or
    # an envelope. Normalise.
    if isinstance(items_raw, dict) and "items" in items_raw:
        items_raw = items_raw["items"]

    # Optional client-side query filter (the API doesn't currently support
    # full-text search; fall back to substring match across workflow + payload).
    items = list(items_raw or [])
    if args.query:
        q = args.query.lower()

        def _match(it: dict[str, Any]) -> bool:
            blob = json.dumps(
                {
                    "workflow": it.get("workflow"),
                    "payload": it.get("payload"),
                    "agent_id": it.get("agent_id"),
                    "id": it.get("id"),
                },
                default=str,
            ).lower()
            return q in blob

        items = [it for it in items if _match(it)]

    summaries = [
        {
            "id": it.get("id"),
            "lane": it.get("lane"),
            "workflow": it.get("workflow"),
            "agent_id": it.get("agent_id"),
            "status": it.get("status"),
            "agent_confidence": it.get("agent_confidence"),
            "sla_due_at": it.get("sla_due_at"),
            "summary": _summarise_payload(it.get("payload")),
        }
        for it in items[: args.limit]
    ]
    return {"items": summaries, "count": len(summaries)}


def _summarise_payload(payload: Any) -> str:
    if not payload:
        return ""
    if isinstance(payload, dict):
        for key in ("subject", "title", "summary", "headline", "rfi_subject"):
            if payload.get(key):
                return str(payload[key])[:200]
        # Fallback — first short string value
        for v in payload.values():
            if isinstance(v, str) and len(v) < 200:
                return v
    return json.dumps(payload, default=str)[:200]


async def _exec_get_approval(
    ctx: ChatContext, raw: dict[str, Any]
) -> dict[str, Any]:
    args = GetApprovalInput.model_validate(raw)
    try:
        item = await ctx.api.get_approval(args.id)
    except QuillAPIError as e:
        if e.status == 404:
            return {"error": "not_found", "id": args.id}
        return {"error": f"API error {e.status}", "id": args.id}
    # Strip noisy raw fields; keep what Claude needs.
    keep = (
        "id",
        "workflow",
        "agent_id",
        "lane",
        "status",
        "priority",
        "sla_due_at",
        "agent_confidence",
        "agent_reasoning",
        "agent_model",
        "created_at",
        "executed_at",
        "payload",
        "citations",
    )
    return {k: item.get(k) for k in keep if k in item}


async def _exec_get_audit(
    ctx: ChatContext, raw: dict[str, Any]
) -> dict[str, Any]:
    args = GetAuditInput.model_validate(raw)
    params: dict[str, Any] = {"limit": args.limit}
    if args.approval_id:
        params["approval_id"] = args.approval_id
    if args.since:
        params["since"] = args.since
    if args.action_type:
        params["action_type"] = args.action_type
    try:
        items = await ctx.api._req("GET", "/v1/audit/recent", params=params)
    except QuillAPIError as e:
        return {"error": f"API error {e.status}", "items": []}
    if isinstance(items, dict) and "items" in items:
        items = items["items"]
    return {"items": items or [], "count": len(items or [])}


async def _exec_get_agent_status(
    ctx: ChatContext, raw: dict[str, Any]
) -> dict[str, Any]:
    args = GetAgentStatusInput.model_validate(raw)
    try:
        agents = await ctx.api._req("GET", "/v1/admin/agents", admin=True)
    except QuillAPIError as e:
        return {"error": f"API error {e.status}", "agents": []}
    if isinstance(agents, dict) and "items" in agents:
        agents = agents["items"]
    if args.agent_id:
        agents = [a for a in (agents or []) if a.get("id") == args.agent_id]
    return {"agents": agents or [], "count": len(agents or [])}


async def _exec_get_health(
    ctx: ChatContext, raw: dict[str, Any]
) -> dict[str, Any]:
    try:
        h = await ctx.api.health()
    except QuillAPIError as e:
        return {"error": f"API error {e.status}"}
    return h


async def _exec_dispatch_agent(
    ctx: ChatContext, raw: dict[str, Any]
) -> dict[str, Any]:
    """Dispatch an agent in DRY-RUN mode and return its output.

    This never writes to the queue. The handler layer is responsible for
    asking the user to confirm a non-dry-run dispatch (which submits to
    the queue and produces an approval item).
    """
    args = DispatchAgentInput.model_validate(raw)

    runtime_bin = os.environ.get("QUILL_RUNTIME_BIN") or shutil.which("quill-runtime")
    if not runtime_bin:
        return {
            "error": "runtime_not_available",
            "message": "quill-runtime is not on PATH; cannot dispatch.",
        }
    cmd = [runtime_bin, "run", args.agent_id, "--input", "-", "--no-submit"]
    payload_bytes = json.dumps(args.input_payload).encode("utf-8")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=payload_bytes), timeout=120
        )
    except asyncio.TimeoutError:
        return {"error": "timeout", "message": "agent dispatch exceeded 120s"}
    except FileNotFoundError as e:
        return {"error": "runtime_not_available", "message": str(e)}

    if proc.returncode != 0:
        return {
            "error": "agent_failed",
            "returncode": proc.returncode,
            "stderr": stderr.decode("utf-8", errors="replace")[:1000],
            "summary": args.summary,
        }
    try:
        output = json.loads(stdout.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        output = {"raw": stdout.decode("utf-8", errors="replace")[:2000]}
    return {
        "agent_id": args.agent_id,
        "dry_run": True,
        "output": output,
        "summary": args.summary,
        "command": shlex.join(cmd),
    }


async def _exec_generate_deep_link(
    ctx: ChatContext, raw: dict[str, Any]
) -> dict[str, Any]:
    args = GenerateDeepLinkInput.model_validate(raw)
    if args.intent == "view":
        # The web doesn't require a passkey to view; produce a plain URL.
        url = f"{ctx.config.quill_web_base_url.rstrip('/')}/approvals/{args.approval_id}"
        return {"url": url, "ttl_seconds": 0, "intent": "view"}
    extra = {"reason": args.reason} if args.reason else None
    url = make_deeplink(
        approval_id=args.approval_id,
        intent=args.intent,
        secret=ctx.config.deeplink_signing_secret,
        base_url=ctx.config.quill_web_base_url,
        user_id=ctx.user_id,
        ttl_seconds=ctx.config.deeplink_ttl_seconds,
        extra=extra,
    )
    return {
        "url": url,
        "ttl_seconds": ctx.config.deeplink_ttl_seconds,
        "intent": args.intent,
        "approval_id": args.approval_id,
    }


async def _exec_current_time(
    ctx: ChatContext, raw: dict[str, Any]
) -> dict[str, Any]:
    CurrentTimeInput.model_validate(raw)
    tz = ZoneInfo("America/New_York")
    now_local = datetime.now(tz)
    return {
        "now": datetime.now(UTC).isoformat(),
        "now_local": now_local.isoformat(),
        "day_of_week": now_local.strftime("%A"),
        "tz": "America/New_York",
    }


async def _exec_whoami(ctx: ChatContext, raw: dict[str, Any]) -> dict[str, Any]:
    WhoamiInput.model_validate(raw)
    try:
        # The API exposes user lookup via the admin pair endpoint indirectly;
        # for whoami, we look up by chat_id via a dedicated admin route if present,
        # otherwise we report the chat-side identity only.
        info = await ctx.api._req(
            "GET",
            f"/v1/admin/users/by_chat/{ctx.chat_id}",
            admin=True,
        )
        return {
            "chat_id": ctx.chat_id,
            "user_id": info.get("user_id") or ctx.user_id,
            "email": info.get("email"),
            "role": info.get("role"),
            "paired": True,
        }
    except QuillAPIError as e:
        if e.status == 404:
            return {
                "chat_id": ctx.chat_id,
                "user_id": ctx.user_id,
                "paired": False,
            }
        return {"chat_id": ctx.chat_id, "error": f"API error {e.status}"}


# ---------------------------------------------------------------------------
# Schema dicts (Anthropic tool input_schema).
# ---------------------------------------------------------------------------
SEARCH_APPROVALS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Free-text substring to filter approvals by workflow / payload / agent.",
        },
        "lane": {
            "type": "integer",
            "enum": [1, 2, 3],
            "description": "Filter by lane: 1=auto, 2=single-sig, 3=dual-sig.",
        },
        "status": {
            "type": "string",
            "description": "Filter by status (pending|executed|cancelled|rejected). Default: pending.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 50,
            "default": 10,
        },
    },
    "additionalProperties": False,
}

GET_APPROVAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {
            "type": "string",
            "description": "Approval item ID (UUID or short prefix is OK).",
        }
    },
    "required": ["id"],
    "additionalProperties": False,
}

GET_AUDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "approval_id": {"type": "string"},
        "since": {
            "type": "string",
            "description": "ISO-8601 timestamp lower bound.",
        },
        "action_type": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
    },
    "additionalProperties": False,
}

GET_AGENT_STATUS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "agent_id": {
            "type": "string",
            "description": "Specific agent ID to fetch; omit to list all agents.",
        }
    },
    "additionalProperties": False,
}

GET_HEALTH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

DISPATCH_AGENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "agent_id": {
            "type": "string",
            "description": "Registered agent ID to run (e.g. 'rfi-triage').",
        },
        "input_payload": {
            "type": "object",
            "description": "JSON object passed as the agent's input.",
        },
        "summary": {
            "type": "string",
            "description": "One-sentence rationale shown to the user before confirming.",
        },
    },
    "required": ["agent_id", "input_payload", "summary"],
    "additionalProperties": False,
}

GENERATE_DEEP_LINK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "approval_id": {"type": "string"},
        "intent": {
            "type": "string",
            "enum": ["approve", "reject", "edit", "view"],
        },
        "reason": {
            "type": "string",
            "description": "Reason text — required for reject, optional for others.",
        },
    },
    "required": ["approval_id", "intent"],
    "additionalProperties": False,
}

CURRENT_TIME_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

WHOAMI_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Registry.
# ---------------------------------------------------------------------------
TOOL_REGISTRY: dict[str, ToolSpec] = {
    "search_approvals": ToolSpec(
        name="search_approvals",
        description=(
            "Search the Approval Queue. Returns compact summaries (id, lane, "
            "workflow, status, summary). Use this any time the user asks "
            "what's pending, what's blocked, or for a specific item."
        ),
        input_schema=SEARCH_APPROVALS_SCHEMA,
        input_model=SearchApprovalsInput,
        executor=_exec_search_approvals,
    ),
    "get_approval": ToolSpec(
        name="get_approval",
        description=(
            "Fetch full detail for one approval by ID, including payload, "
            "citations, agent reasoning, and current status."
        ),
        input_schema=GET_APPROVAL_SCHEMA,
        input_model=GetApprovalInput,
        executor=_exec_get_approval,
    ),
    "get_audit": ToolSpec(
        name="get_audit",
        description=(
            "List recent audit log entries. Filter by approval_id, action_type, "
            "or since-timestamp. Use to answer 'what happened with X?' or "
            "'what did I sign yesterday?'."
        ),
        input_schema=GET_AUDIT_SCHEMA,
        input_model=GetAuditInput,
        executor=_exec_get_audit,
    ),
    "get_agent_status": ToolSpec(
        name="get_agent_status",
        description=(
            "Get registered-agent metadata. Omit agent_id to list all agents."
        ),
        input_schema=GET_AGENT_STATUS_SCHEMA,
        input_model=GetAgentStatusInput,
        executor=_exec_get_agent_status,
    ),
    "get_health": ToolSpec(
        name="get_health",
        description=(
            "Fleet health snapshot — DB, audit chain, queue depth, SLA "
            "breaches, version. Use for 'is everything ok?'."
        ),
        input_schema=GET_HEALTH_SCHEMA,
        input_model=GetHealthInput,
        executor=_exec_get_health,
    ),
    "dispatch_agent": ToolSpec(
        name="dispatch_agent",
        description=(
            "Dispatch a Quill agent in DRY-RUN mode against a JSON input. "
            "Returns the agent's output without writing to the queue. "
            "ALWAYS describe what you propose to do before calling this and "
            "let the user confirm — non-dry-run execution is gated at the "
            "handler layer with an inline-keyboard confirmation."
        ),
        input_schema=DISPATCH_AGENT_SCHEMA,
        input_model=DispatchAgentInput,
        executor=_exec_dispatch_agent,
    ),
    "generate_deep_link": ToolSpec(
        name="generate_deep_link",
        description=(
            "Produce a short-lived signed URL that opens the web UI's "
            "passkey ceremony for an approval. Use for any approve/reject/"
            "edit intent — you cannot approve from chat."
        ),
        input_schema=GENERATE_DEEP_LINK_SCHEMA,
        input_model=GenerateDeepLinkInput,
        executor=_exec_generate_deep_link,
    ),
    "current_time": ToolSpec(
        name="current_time",
        description=(
            "Returns current ISO timestamp, day-of-week, and Charles's tz "
            "(America/New_York). Use when the user asks about 'today', "
            "'yesterday', or scheduling."
        ),
        input_schema=CURRENT_TIME_SCHEMA,
        input_model=CurrentTimeInput,
        executor=_exec_current_time,
    ),
    "whoami": ToolSpec(
        name="whoami",
        description=(
            "Resolve the current chat to a Quill user (email, role). "
            "Use to personalise replies; if unpaired, the bot will instruct "
            "the user to pair first."
        ),
        input_schema=WHOAMI_SCHEMA,
        input_model=WhoamiInput,
        executor=_exec_whoami,
    ),
}


def anthropic_tool_specs() -> list[dict[str, Any]]:
    """Return all tool specs in Anthropic's tool-use schema format."""
    return [t.to_anthropic() for t in TOOL_REGISTRY.values()]


async def execute_tool(
    name: str, raw_input: dict[str, Any], ctx: ChatContext
) -> dict[str, Any]:
    """Validate input, execute, and return the JSON result.

    On validation failure returns an error envelope rather than raising,
    so Claude can recover gracefully on the next turn.
    """
    spec = TOOL_REGISTRY.get(name)
    if spec is None:
        return {"error": "unknown_tool", "tool": name}
    try:
        spec.input_model.model_validate(raw_input)
    except ValidationError as e:
        return {
            "error": "invalid_input",
            "tool": name,
            "detail": json.loads(e.json()),
        }
    try:
        return await spec.executor(ctx, raw_input)
    except Exception as e:  # noqa: BLE001 — surface to Claude, don't crash
        log.exception("tool_executor_failed", extra={"tool": name})
        return {"error": "tool_exception", "tool": name, "detail": str(e)}


__all__ = [
    "ChatContext",
    "ToolSpec",
    "TOOL_REGISTRY",
    "anthropic_tool_specs",
    "execute_tool",
    # input models exported for external typing if desired
    "SearchApprovalsInput",
    "GetApprovalInput",
    "GetAuditInput",
    "GetAgentStatusInput",
    "GetHealthInput",
    "DispatchAgentInput",
    "GenerateDeepLinkInput",
    "CurrentTimeInput",
    "WhoamiInput",
]
