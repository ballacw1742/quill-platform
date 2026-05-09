"""Tests for the estimates tool executors (Phase G.3, Commit 1).

Each tool round-trips through a mocked ApiClient and verifies the
documented reply shape. Three tools:
  - get_estimate_status
  - list_recent_estimates
  - estimate_upload_link
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
# Fake API client tailored for the estimate tools. Only implements the
# methods the new tools call.
# ---------------------------------------------------------------------------
class FakeAPIForEstimates:
    def __init__(self) -> None:
        self.statuses: dict[str, dict[str, Any]] = {}
        self.documents: list[dict[str, Any]] = []
        self.list_calls: list[int] = []
        self.status_calls: list[str] = []
        # Optional: force these exceptions on next call.
        self.raise_on_status: QuillAPIError | None = None
        self.raise_on_list: QuillAPIError | None = None

    async def get_estimate_status(self, upload_id: str) -> dict[str, Any]:
        self.status_calls.append(upload_id)
        if self.raise_on_status is not None:
            raise self.raise_on_status
        if upload_id not in self.statuses:
            raise QuillAPIError(404, "upload not found")
        return self.statuses[upload_id]

    async def list_estimates(self, limit: int = 10) -> list[dict[str, Any]]:
        self.list_calls.append(limit)
        if self.raise_on_list is not None:
            raise self.raise_on_list
        return list(self.documents[:limit])


@pytest.fixture
def ctx(bot_config: BotConfig) -> ChatContext:
    return ChatContext(
        api=FakeAPIForEstimates(),  # type: ignore[arg-type]
        config=bot_config,
        chat_id=1234567,
        user_id="u-test",
    )


# ---------------------------------------------------------------------------
# Registry sanity
# ---------------------------------------------------------------------------
def test_estimate_tools_registered() -> None:
    for name in ("get_estimate_status", "list_recent_estimates", "estimate_upload_link"):
        assert name in TOOL_REGISTRY, f"{name} should be in TOOL_REGISTRY"


def test_estimate_tools_have_anthropic_schema() -> None:
    for name in ("get_estimate_status", "list_recent_estimates", "estimate_upload_link"):
        spec = TOOL_REGISTRY[name]
        schema = spec.to_anthropic()
        assert schema["name"] == name
        assert "input_schema" in schema
        assert schema["input_schema"]["type"] == "object"


# ---------------------------------------------------------------------------
# get_estimate_status
# ---------------------------------------------------------------------------
async def test_get_estimate_status_round_trip(ctx: ChatContext) -> None:
    ctx.api.statuses["upl-abc"] = {  # type: ignore[attr-defined]
        "upload_id": "upl-abc",
        "status": "estimating",
        "project_label": "DC1 Switchgear",
        "notes": "rev B",
        "uploaded_files": [
            {
                "filename": "drawing-1.pdf",
                "kind": "pdf",
                "extraction_status": "done",
            },
            {
                "filename": "model.ifc",
                "kind": "ifc",
                "extraction_status": "pending",
            },
        ],
        "classification_artifact_id": "art-class-1",
        "package_artifact_id": None,
        "created_at": "2026-05-08T20:00:00+00:00",
        "updated_at": "2026-05-08T21:30:00+00:00",
        "error_message": None,
    }
    out = await execute_tool("get_estimate_status", {"upload_id": "upl-abc"}, ctx)
    assert out["upload_id"] == "upl-abc"
    assert out["status"] == "estimating"
    assert out["project_label"] == "DC1 Switchgear"
    assert out["classification_artifact_id"] == "art-class-1"
    assert out["package_artifact_id"] is None
    assert out["file_count"] == 2
    assert out["files"][0]["filename"] == "drawing-1.pdf"
    assert out["files"][0]["extraction_status"] == "done"
    # Confirms the call hit our fake client
    assert ctx.api.status_calls == ["upl-abc"]  # type: ignore[attr-defined]


async def test_get_estimate_status_404(ctx: ChatContext) -> None:
    out = await execute_tool("get_estimate_status", {"upload_id": "missing"}, ctx)
    assert out == {"error": "not_found", "upload_id": "missing"}


async def test_get_estimate_status_401_returns_helpful_error(ctx: ChatContext) -> None:
    ctx.api.raise_on_status = QuillAPIError(401, "missing bearer token")  # type: ignore[attr-defined]
    out = await execute_tool("get_estimate_status", {"upload_id": "u1"}, ctx)
    assert out["error"] == "unauthorized"
    assert out["upload_id"] == "u1"
    assert "KNOWN_ISSUES" in out["detail"]


async def test_get_estimate_status_other_api_error(ctx: ChatContext) -> None:
    ctx.api.raise_on_status = QuillAPIError(503, "upstream down")  # type: ignore[attr-defined]
    out = await execute_tool("get_estimate_status", {"upload_id": "u1"}, ctx)
    assert out["error"].startswith("API error 503")
    assert out["upload_id"] == "u1"


async def test_get_estimate_status_invalid_input(ctx: ChatContext) -> None:
    out = await execute_tool("get_estimate_status", {}, ctx)
    assert out["error"] == "invalid_input"
    assert out["tool"] == "get_estimate_status"


# ---------------------------------------------------------------------------
# list_recent_estimates
# ---------------------------------------------------------------------------
async def test_list_recent_estimates_round_trip(ctx: ChatContext) -> None:
    ctx.api.documents = [  # type: ignore[attr-defined]
        {
            "id": "doc-1",
            "artifact_id": "art-1",
            "artifact_type": "aace_classification",
            "title": "DC1 Switchgear — AACE Class 4",
            "agent_id": "drawings-classifier",
            "created_at": "2026-05-08T20:00:00+00:00",
            "tags": ["upload:upl-abc", "estimate"],
            "summary": "Class 4 estimate, parametric, ±50% accuracy",
        },
        {
            "id": "doc-2",
            "artifact_id": "art-2",
            "artifact_type": "cost_schedule_package",
            "title": "DC1 Switchgear — Cost & Schedule Package",
            "agent_id": "estimator-scheduler",
            "created_at": "2026-05-08T22:00:00+00:00",
            "tags": ["upload:upl-abc"],
            "summary": "$12.4M, 18 months, 14 line items",
        },
    ]
    out = await execute_tool("list_recent_estimates", {"limit": 5}, ctx)
    assert out["count"] == 2
    titles = [it["title"] for it in out["items"]]
    assert "DC1 Switchgear — AACE Class 4" in titles
    types = {it["artifact_type"] for it in out["items"]}
    assert types == {"aace_classification", "cost_schedule_package"}
    upload_ids = {it["upload_id"] for it in out["items"]}
    assert upload_ids == {"upl-abc"}
    assert ctx.api.list_calls == [5]  # type: ignore[attr-defined]


async def test_list_recent_estimates_default_limit(ctx: ChatContext) -> None:
    ctx.api.documents = []  # type: ignore[attr-defined]
    out = await execute_tool("list_recent_estimates", {}, ctx)
    assert out == {"items": [], "count": 0}
    assert ctx.api.list_calls == [10]  # type: ignore[attr-defined]


async def test_list_recent_estimates_extracts_upload_id_from_meta(ctx: ChatContext) -> None:
    ctx.api.documents = [  # type: ignore[attr-defined]
        {
            "id": "doc-x",
            "artifact_id": "art-x",
            "artifact_type": "aace_classification",
            "title": "T",
            "tags": [],
            "meta": {"upload_id": "upl-from-meta"},
            "summary": "",
        }
    ]
    out = await execute_tool("list_recent_estimates", {}, ctx)
    assert out["items"][0]["upload_id"] == "upl-from-meta"


async def test_list_recent_estimates_unknown_upload_id_is_none(ctx: ChatContext) -> None:
    ctx.api.documents = [  # type: ignore[attr-defined]
        {
            "id": "doc-y",
            "artifact_id": "art-y",
            "artifact_type": "aace_classification",
            "title": "T",
            "tags": ["unrelated:tag"],
            "summary": "",
        }
    ]
    out = await execute_tool("list_recent_estimates", {}, ctx)
    assert out["items"][0]["upload_id"] is None


async def test_list_recent_estimates_401(ctx: ChatContext) -> None:
    ctx.api.raise_on_list = QuillAPIError(401, "missing bearer token")  # type: ignore[attr-defined]
    out = await execute_tool("list_recent_estimates", {}, ctx)
    assert out["error"] == "unauthorized"
    assert out["items"] == []
    assert "KNOWN_ISSUES" in out["detail"]


async def test_list_recent_estimates_invalid_limit(ctx: ChatContext) -> None:
    out = await execute_tool("list_recent_estimates", {"limit": 999}, ctx)
    assert out["error"] == "invalid_input"


# ---------------------------------------------------------------------------
# estimate_upload_link
# ---------------------------------------------------------------------------
async def test_estimate_upload_link_returns_url(ctx: ChatContext) -> None:
    out = await execute_tool("estimate_upload_link", {}, ctx)
    assert out["url"].endswith("/today")
    # bot config defaults to https://web.test in conftest
    assert "web.test" in out["url"]
    assert "Estimate from drawings" in out["instructions"]
    assert out["note"] == "file upload is web-app-only"


async def test_estimate_upload_link_does_not_call_api(ctx: ChatContext) -> None:
    await execute_tool("estimate_upload_link", {}, ctx)
    assert ctx.api.status_calls == []  # type: ignore[attr-defined]
    assert ctx.api.list_calls == []  # type: ignore[attr-defined]
