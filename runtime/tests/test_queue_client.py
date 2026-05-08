from __future__ import annotations

import json

import httpx
import pytest

from runtime.config import Config
from runtime.queue_client import QueueClient, QueueClientError


def _build_client(handler):
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(base_url="http://test", transport=transport)
    cfg = Config(
        prompts_repo_path=None,  # type: ignore[arg-type]
        queue_api_url="http://test",
        agent_shared_secret="s3cret",
        anthropic_api_key="x",
        log_level="WARNING",
    )
    return QueueClient(cfg, client=http)


@pytest.mark.asyncio
async def test_create_approval_sends_secret_and_returns_body():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(req.headers)
        captured["body"] = json.loads(req.content)
        return httpx.Response(
            201, json={"id": "appr-123", "lane": captured["body"]["lane"]}
        )

    client = _build_client(handler)
    resp = await client.create_approval(
        {
            "agent_id": "rfi-triage",
            "agent_version": "0.1.0",
            "workflow": "rfi-triage",
            "lane": 2,
            "payload": {"x": 1},
            "agent_confidence": 0.9,
            "internal_only": "ignored",
        }
    )
    assert resp["id"] == "appr-123"
    assert captured["headers"]["x-agent-secret"] == "s3cret"
    assert captured["headers"]["authorization"] == "Bearer s3cret"
    # Adapter stripped unknown keys
    assert "internal_only" not in captured["body"]
    await client.aclose()


@pytest.mark.asyncio
async def test_get_approval():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/approvals/appr-1"
        return httpx.Response(200, json={"id": "appr-1", "status": "pending"})

    client = _build_client(handler)
    out = await client.get_approval("appr-1")
    assert out["id"] == "appr-1"
    await client.aclose()


@pytest.mark.asyncio
async def test_list_pending_passes_filters():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/approvals"
        assert req.url.params["lane"] == "2"
        assert req.url.params["status"] == "pending"
        return httpx.Response(200, json={"items": [], "total": 0, "limit": 50, "offset": 0})

    client = _build_client(handler)
    out = await client.list_pending(lane=2)
    assert out["total"] == 0
    await client.aclose()


@pytest.mark.asyncio
async def test_cancel_propagates_reason():
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else {}
        assert body == {"reason": "no longer needed"}
        return httpx.Response(200, json={"id": "appr-1", "status": "cancelled"})

    client = _build_client(handler)
    out = await client.cancel("appr-1", "no longer needed")
    assert out["status"] == "cancelled"
    await client.aclose()


@pytest.mark.asyncio
async def test_http_error_raises():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad secret")

    client = _build_client(handler)
    with pytest.raises(QueueClientError):
        await client.create_approval(
            {
                "agent_id": "x",
                "agent_version": "1",
                "workflow": "x",
                "lane": 2,
                "payload": {},
                "agent_confidence": 1.0,
            }
        )
    await client.aclose()
