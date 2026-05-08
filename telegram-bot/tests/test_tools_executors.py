"""Tests for tool executors (Phase B, Commit 3).

Each tool round-trips through a mocked ApiClient (or environment) and
produces the documented reply shape.
"""

from __future__ import annotations

from typing import Any

import pytest

from quill_bot.api_client import QuillAPIError
from quill_bot.config import BotConfig
from quill_bot.tools import (
    ChatContext,
    TOOL_REGISTRY,
    execute_tool,
)


# ---------------------------------------------------------------------------
# A small fake ApiClient that supports the methods the tools use, including
# the lower-level _req helper (used by search/audit/agents/whoami).
# ---------------------------------------------------------------------------
class FakeAPIForTools:
    def __init__(self) -> None:
        self.pending: list[dict[str, Any]] = []
        self.executed: list[dict[str, Any]] = []
        self.audit_rows: list[dict[str, Any]] = []
        self.agents: list[dict[str, Any]] = []
        self.health_state = {
            "ok": True,
            "db": "ok",
            "queue_depth_pending": 1,
            "queue_depth_executed": 0,
            "audit_chain": "ok",
            "audit_chain_length": 1,
            "sla_breaches_open": 0,
            "version": "0.1.0",
        }
        self.user_by_chat: dict[int, dict[str, Any]] = {}
        self.req_calls: list[tuple[str, str, dict[str, Any]]] = []

    async def list_pending(
        self, *, lane: int | None = None, limit: int = 5, offset: int = 0
    ) -> list[dict[str, Any]]:
        items = [it for it in self.pending if lane is None or it.get("lane") == lane]
        return items[offset : offset + limit]

    async def get_approval(self, approval_id: str) -> dict[str, Any]:
        for it in self.pending + self.executed:
            if it.get("id") == approval_id:
                return it
        raise QuillAPIError(404, "not found")

    async def health(self) -> dict[str, Any]:
        return self.health_state

    async def _req(
        self,
        method: str,
        path: str,
        *,
        admin: bool = False,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        self.req_calls.append((method, path, dict(params or {})))
        if path == "/v1/approvals" and method == "GET":
            status = (params or {}).get("status", "pending")
            pool = self.pending if status == "pending" else self.executed
            return {
                "items": pool,
                "total": len(pool),
                "limit": (params or {}).get("limit", 10),
                "offset": 0,
            }
        if path == "/v1/audit/recent" and method == "GET":
            return list(self.audit_rows)
        if path == "/v1/admin/agents" and method == "GET":
            return list(self.agents)
        if path.startswith("/v1/admin/users/by_chat/"):
            chat_id = int(path.rsplit("/", 1)[-1])
            if chat_id in self.user_by_chat:
                return self.user_by_chat[chat_id]
            raise QuillAPIError(404, "not found")
        raise QuillAPIError(404, f"unmocked {method} {path}")


@pytest.fixture
def ctx(bot_config: BotConfig) -> ChatContext:
    return ChatContext(
        api=FakeAPIForTools(),  # type: ignore[arg-type]
        config=bot_config,
        chat_id=1234567,
        user_id="u-test",
    )


# ---------------------------------------------------------------------------
# search_approvals
# ---------------------------------------------------------------------------
async def test_search_approvals_pending_path(ctx: ChatContext) -> None:
    ctx.api.pending = [  # type: ignore[attr-defined]
        {
            "id": "ap-1",
            "lane": 2,
            "workflow": "rfi-triage",
            "agent_id": "rfi-triage",
            "status": "pending",
            "agent_confidence": 0.92,
            "sla_due_at": "2026-05-09T00:00:00Z",
            "payload": {"subject": "Chiller dunnage on roof — clarify"},
        },
        {
            "id": "ap-2",
            "lane": 3,
            "workflow": "submittal-review",
            "status": "pending",
            "payload": {"subject": "Submittal-DC1-A-0234 review"},
        },
    ]
    out = await execute_tool("search_approvals", {}, ctx)
    assert out["count"] == 2
    assert out["items"][0]["id"] == "ap-1"
    assert "Chiller" in out["items"][0]["summary"]


async def test_search_approvals_query_filter(ctx: ChatContext) -> None:
    ctx.api.pending = [  # type: ignore[attr-defined]
        {"id": "ap-1", "workflow": "rfi-triage", "payload": {"subject": "Chiller dunnage"}},
        {"id": "ap-2", "workflow": "submittal-review", "payload": {"subject": "Door schedule"}},
    ]
    out = await execute_tool("search_approvals", {"query": "chiller"}, ctx)
    assert out["count"] == 1
    assert out["items"][0]["id"] == "ap-1"


async def test_search_approvals_lane_passes_through(ctx: ChatContext) -> None:
    ctx.api.pending = [  # type: ignore[attr-defined]
        {"id": "ap-1", "lane": 2, "workflow": "x", "payload": {}},
        {"id": "ap-2", "lane": 3, "workflow": "y", "payload": {}},
    ]
    out = await execute_tool("search_approvals", {"lane": 3}, ctx)
    assert {it["id"] for it in out["items"]} == {"ap-2"}


async def test_search_approvals_status_executed_uses_envelope(ctx: ChatContext) -> None:
    ctx.api.executed = [{"id": "ap-9", "status": "executed", "workflow": "x"}]  # type: ignore[attr-defined]
    out = await execute_tool("search_approvals", {"status": "executed"}, ctx)
    assert out["count"] == 1
    # confirms it called the envelope endpoint
    calls = ctx.api.req_calls  # type: ignore[attr-defined]
    assert any(c[1] == "/v1/approvals" for c in calls)


# ---------------------------------------------------------------------------
# get_approval
# ---------------------------------------------------------------------------
async def test_get_approval_round_trip(ctx: ChatContext) -> None:
    ctx.api.pending = [{  # type: ignore[attr-defined]
        "id": "ap-7",
        "workflow": "rfi-triage",
        "agent_id": "rfi-triage",
        "lane": 2,
        "status": "pending",
        "priority": "normal",
        "agent_confidence": 0.91,
        "agent_reasoning": "high cite coverage",
        "payload": {"subject": "Test"},
        "citations": [],
    }]
    out = await execute_tool("get_approval", {"id": "ap-7"}, ctx)
    assert out["id"] == "ap-7"
    assert out["agent_confidence"] == 0.91
    assert out["payload"]["subject"] == "Test"


async def test_get_approval_404_returns_error_envelope(ctx: ChatContext) -> None:
    out = await execute_tool("get_approval", {"id": "missing"}, ctx)
    assert out == {"error": "not_found", "id": "missing"}


# ---------------------------------------------------------------------------
# get_audit
# ---------------------------------------------------------------------------
async def test_get_audit_passes_filters(ctx: ChatContext) -> None:
    ctx.api.audit_rows = [{"id": "log-1", "action_type": "approve", "approval_id": "ap-1"}]  # type: ignore[attr-defined]
    out = await execute_tool(
        "get_audit",
        {"approval_id": "ap-1", "action_type": "approve", "limit": 5},
        ctx,
    )
    assert out["count"] == 1
    assert out["items"][0]["id"] == "log-1"
    # params got through
    method, path, params = ctx.api.req_calls[-1]  # type: ignore[attr-defined]
    assert path == "/v1/audit/recent"
    assert params["approval_id"] == "ap-1"
    assert params["action_type"] == "approve"


# ---------------------------------------------------------------------------
# get_agent_status
# ---------------------------------------------------------------------------
async def test_get_agent_status_lists_all(ctx: ChatContext) -> None:
    ctx.api.agents = [  # type: ignore[attr-defined]
        {"id": "rfi-triage", "name": "RFI Triage", "is_active": True},
        {"id": "submittal-review", "name": "Submittal Review", "is_active": False},
    ]
    out = await execute_tool("get_agent_status", {}, ctx)
    assert out["count"] == 2


async def test_get_agent_status_filter_by_id(ctx: ChatContext) -> None:
    ctx.api.agents = [  # type: ignore[attr-defined]
        {"id": "rfi-triage", "name": "RFI Triage"},
        {"id": "submittal-review", "name": "Submittal Review"},
    ]
    out = await execute_tool("get_agent_status", {"agent_id": "rfi-triage"}, ctx)
    assert out["count"] == 1
    assert out["agents"][0]["id"] == "rfi-triage"


# ---------------------------------------------------------------------------
# get_health
# ---------------------------------------------------------------------------
async def test_get_health(ctx: ChatContext) -> None:
    out = await execute_tool("get_health", {}, ctx)
    assert out["ok"] is True
    assert "audit_chain" in out


# ---------------------------------------------------------------------------
# generate_deep_link
# ---------------------------------------------------------------------------
async def test_generate_deep_link_approve(ctx: ChatContext) -> None:
    out = await execute_tool(
        "generate_deep_link",
        {"approval_id": "ap-1", "intent": "approve"},
        ctx,
    )
    assert out["intent"] == "approve"
    assert out["approval_id"] == "ap-1"
    assert "/approvals/ap-1/approve?t=" in out["url"]
    assert out["ttl_seconds"] == ctx.config.deeplink_ttl_seconds


async def test_generate_deep_link_view_no_signature(ctx: ChatContext) -> None:
    out = await execute_tool(
        "generate_deep_link", {"approval_id": "ap-9", "intent": "view"}, ctx
    )
    assert out["intent"] == "view"
    assert out["url"].endswith("/approvals/ap-9")
    assert out["ttl_seconds"] == 0


async def test_generate_deep_link_reject_includes_reason(ctx: ChatContext) -> None:
    out = await execute_tool(
        "generate_deep_link",
        {"approval_id": "ap-1", "intent": "reject", "reason": "needs spec ref"},
        ctx,
    )
    # reason is embedded in the signed payload — we don't decode here, but we
    # confirm the link was produced and is non-empty.
    assert out["intent"] == "reject"
    assert "/approvals/ap-1/reject?t=" in out["url"]


async def test_generate_deep_link_invalid_intent(ctx: ChatContext) -> None:
    out = await execute_tool(
        "generate_deep_link",
        {"approval_id": "ap-1", "intent": "delete"},  # not in enum
        ctx,
    )
    assert out["error"] == "invalid_input"


# ---------------------------------------------------------------------------
# current_time
# ---------------------------------------------------------------------------
async def test_current_time(ctx: ChatContext) -> None:
    out = await execute_tool("current_time", {}, ctx)
    assert out["tz"] == "America/New_York"
    assert "T" in out["now"]
    assert out["day_of_week"] in {
        "Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday", "Saturday", "Sunday",
    }


# ---------------------------------------------------------------------------
# whoami
# ---------------------------------------------------------------------------
async def test_whoami_paired(ctx: ChatContext) -> None:
    ctx.api.user_by_chat = {  # type: ignore[attr-defined]
        1234567: {"user_id": "u-1", "email": "charles@example.com", "role": "owner"},
    }
    out = await execute_tool("whoami", {}, ctx)
    assert out["paired"] is True
    assert out["email"] == "charles@example.com"


async def test_whoami_unpaired(ctx: ChatContext) -> None:
    out = await execute_tool("whoami", {}, ctx)  # no user mapping
    assert out["paired"] is False
    assert out["chat_id"] == 1234567


# ---------------------------------------------------------------------------
# dispatch_agent — runtime not necessarily on PATH in CI
# ---------------------------------------------------------------------------
async def test_dispatch_agent_runtime_missing(monkeypatch, ctx: ChatContext) -> None:
    monkeypatch.setenv("QUILL_RUNTIME_BIN", "")  # force the shutil.which path
    monkeypatch.setattr("shutil.which", lambda x: None)
    out = await execute_tool(
        "dispatch_agent",
        {"agent_id": "rfi-triage", "input_payload": {"x": 1}, "summary": "test"},
        ctx,
    )
    assert out["error"] == "runtime_not_available"


async def test_dispatch_agent_invokes_subprocess(monkeypatch, ctx: ChatContext) -> None:
    """When the runtime is present, dispatch_agent invokes it in --no-submit mode."""

    captured: dict[str, Any] = {}

    class FakeProc:
        returncode = 0

        async def communicate(self, input: bytes = b"") -> tuple[bytes, bytes]:
            captured["stdin"] = input
            return (b'{"draft": "ok"}', b"")

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["argv"] = list(args)
        return FakeProc()

    monkeypatch.setenv("QUILL_RUNTIME_BIN", "/usr/local/bin/quill-runtime")
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    out = await execute_tool(
        "dispatch_agent",
        {
            "agent_id": "status-update-author",
            "input_payload": {"week": "2026-W19"},
            "summary": "draft weekly status",
        },
        ctx,
    )
    assert out["dry_run"] is True
    assert out["agent_id"] == "status-update-author"
    assert out["output"] == {"draft": "ok"}
    assert "--no-submit" in captured["argv"]
    assert "--input" in captured["argv"]


# ---------------------------------------------------------------------------
# Validation / generic
# ---------------------------------------------------------------------------
async def test_unknown_tool(ctx: ChatContext) -> None:
    out = await execute_tool("not_a_tool", {}, ctx)
    assert out == {"error": "unknown_tool", "tool": "not_a_tool"}


async def test_invalid_input_returns_envelope(ctx: ChatContext) -> None:
    out = await execute_tool("get_approval", {}, ctx)  # missing required id
    assert out["error"] == "invalid_input"
    assert out["tool"] == "get_approval"
    assert "detail" in out


async def test_executor_exception_does_not_crash(monkeypatch, ctx: ChatContext) -> None:
    async def boom(c, raw):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(TOOL_REGISTRY["get_health"], "executor", boom)
    out = await execute_tool("get_health", {}, ctx)
    assert out["error"] == "tool_exception"
    assert "kaboom" in out["detail"]
