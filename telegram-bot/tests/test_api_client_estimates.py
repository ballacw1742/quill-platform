"""Tests for QuillAPIClient estimates helpers (Phase G.3, Commit 2)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from quill_bot.api_client import QuillAPIClient, QuillAPIError
from quill_bot.config import BotConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _client(handler) -> QuillAPIClient:
    """Build a QuillAPIClient backed by a MockTransport."""
    cfg = BotConfig.from_env()
    transport = httpx.MockTransport(handler)
    inner = httpx.AsyncClient(
        base_url=cfg.quill_api_url, transport=transport, timeout=2.0
    )
    return QuillAPIClient(cfg, client=inner)


# ---------------------------------------------------------------------------
# get_estimate_status
# ---------------------------------------------------------------------------
async def test_get_estimate_status_hits_correct_path() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        if req.url.path.endswith("/status"):
            return httpx.Response(
                200,
                json={
                    "upload_id": "upl-1",
                    "status": "extracting",
                    "project_label": "DC1",
                    "uploaded_files": [],
                    "classification_artifact_id": None,
                    "package_artifact_id": None,
                    "created_at": "2026-05-08T20:00:00+00:00",
                    "updated_at": "2026-05-08T20:00:00+00:00",
                },
            )
        return httpx.Response(404, json={"detail": "no"})

    api = _client(handler)
    try:
        out = await api.get_estimate_status("upl-1")
    finally:
        await api.aclose()
    assert out["upload_id"] == "upl-1"
    assert out["status"] == "extracting"
    assert seen == ["/v1/estimates/upl-1/status"]


async def test_get_estimate_status_404_raises() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "upload not found"})

    api = _client(handler)
    try:
        with pytest.raises(QuillAPIError) as ei:
            await api.get_estimate_status("missing")
    finally:
        await api.aclose()
    assert ei.value.status == 404


# ---------------------------------------------------------------------------
# list_estimates
# ---------------------------------------------------------------------------
async def test_list_estimates_filters_by_artifact_type() -> None:
    calls: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        params = dict(req.url.params)
        calls.append({"path": req.url.path, "params": params})
        at = params.get("artifact_type")
        if at == "aace_classification":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "doc-1",
                            "artifact_id": "art-1",
                            "artifact_type": "aace_classification",
                            "title": "DC1 Class 4",
                            "created_at": "2026-05-08T20:00:00+00:00",
                            "tags": ["upload:upl-abc"],
                            "summary": "",
                        }
                    ],
                    "total": 1,
                    "limit": 10,
                    "offset": 0,
                },
            )
        if at == "cost_schedule_package":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "doc-2",
                            "artifact_id": "art-2",
                            "artifact_type": "cost_schedule_package",
                            "title": "DC1 C&S",
                            "created_at": "2026-05-08T22:00:00+00:00",
                            "tags": ["upload:upl-abc"],
                            "summary": "",
                        }
                    ],
                    "total": 1,
                    "limit": 10,
                    "offset": 0,
                },
            )
        return httpx.Response(400, json={"detail": "bad filter"})

    api = _client(handler)
    try:
        items = await api.list_estimates(limit=10)
    finally:
        await api.aclose()

    assert len(items) == 2
    # Newest first (cost_schedule_package was created later)
    assert items[0]["id"] == "doc-2"
    assert items[1]["id"] == "doc-1"
    # Two calls: one per artifact type
    types = sorted(c["params"].get("artifact_type", "") for c in calls)
    assert types == ["aace_classification", "cost_schedule_package"]


async def test_list_estimates_respects_limit() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        at = req.url.params.get("artifact_type")
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": f"{at}-{i}",
                        "artifact_type": at,
                        "title": f"t{i}",
                        "created_at": f"2026-05-08T0{i}:00:00+00:00",
                    }
                    for i in range(5)
                ],
                "total": 5,
                "limit": 5,
                "offset": 0,
            },
        )

    api = _client(handler)
    try:
        items = await api.list_estimates(limit=3)
    finally:
        await api.aclose()
    assert len(items) == 3


async def test_list_estimates_falls_back_when_filter_rejected() -> None:
    """If the API doesn't accept artifact_type, we re-fetch unfiltered
    once and filter client-side."""
    calls: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        params = dict(req.url.params)
        calls.append(params)
        if "artifact_type" in params:
            return httpx.Response(400, json={"detail": "unknown filter"})
        # unfiltered fallback
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "doc-1",
                        "artifact_type": "aace_classification",
                        "title": "Class",
                        "created_at": "2026-05-08T20:00:00+00:00",
                    },
                    {
                        "id": "doc-2",
                        "artifact_type": "rfi_response",
                        "title": "RFI",
                        "created_at": "2026-05-08T21:00:00+00:00",
                    },
                    {
                        "id": "doc-3",
                        "artifact_type": "cost_schedule_package",
                        "title": "Pkg",
                        "created_at": "2026-05-08T22:00:00+00:00",
                    },
                ],
                "total": 3,
                "limit": 200,
                "offset": 0,
            },
        )

    api = _client(handler)
    try:
        items = await api.list_estimates(limit=10)
    finally:
        await api.aclose()
    ids = [it["id"] for it in items]
    assert "doc-2" not in ids  # rfi_response excluded
    assert set(ids) == {"doc-1", "doc-3"}


async def test_list_estimates_propagates_other_errors() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    api = _client(handler)
    try:
        with pytest.raises(QuillAPIError) as ei:
            await api.list_estimates(limit=5)
    finally:
        await api.aclose()
    assert ei.value.status == 503
