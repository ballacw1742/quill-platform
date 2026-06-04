"""Unit tests for LocalLLMClient — payload shape, image encoding, warmup."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from runtime.local_llm_client import LocalLLMClient, LocalLLMConfig, LocalLLMError


@pytest.fixture
def cfg() -> LocalLLMConfig:
    return LocalLLMConfig(base_url="http://test.ollama", default_model="m1", timeout_s=10.0)


def _mock_response(json_body: dict[str, Any], status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_body
    resp.text = json.dumps(json_body)
    return resp


def _patch_client(send_mock: AsyncMock):
    ctx = MagicMock()
    inst = MagicMock()
    inst.post = send_mock
    ctx.__aenter__ = AsyncMock(return_value=inst)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return patch("runtime.local_llm_client.httpx.AsyncClient", return_value=ctx)


def test_call_sends_expected_payload(cfg):
    captured = {}

    async def fake_post(url, json=None):
        captured["url"] = url
        captured["body"] = json
        return _mock_response({
            "message": {"content": '{"k":"v"}'},
            "prompt_eval_count": 10,
            "eval_count": 5,
        })

    with _patch_client(AsyncMock(side_effect=fake_post)):
        client = LocalLLMClient(cfg)
        out = asyncio.run(client.call(model="m2", system="sys", user="usr"))

    assert captured["url"] == "http://test.ollama/api/chat"
    body = captured["body"]
    assert body["model"] == "m2"
    assert body["stream"] is False
    assert body["format"] == "json"
    assert body["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    assert out["text"] == '{"k":"v"}'
    assert out["input_tokens"] == 10
    assert out["output_tokens"] == 5
    assert out["model_used"] == "m2"


def test_call_with_images_b64_passthrough(cfg):
    captured = {}

    async def fake_post(url, json=None):
        captured["body"] = json
        return _mock_response({"message": {"content": "{}"}, "prompt_eval_count": 0, "eval_count": 0})

    raw = base64.b64encode(b"fake-png").decode("ascii")
    with _patch_client(AsyncMock(side_effect=fake_post)):
        client = LocalLLMClient(cfg)
        asyncio.run(client.call(model=None, system="s", user="u", images=[raw]))

    user_msg = captured["body"]["messages"][1]
    assert user_msg["images"] == [raw]


def test_call_with_image_file_path(cfg, tmp_path):
    captured = {}
    img_path = tmp_path / "img.png"
    img_path.write_bytes(b"\x89PNG\r\nfake")

    async def fake_post(url, json=None):
        captured["body"] = json
        return _mock_response({"message": {"content": "{}"}, "prompt_eval_count": 0, "eval_count": 0})

    with _patch_client(AsyncMock(side_effect=fake_post)):
        client = LocalLLMClient(cfg)
        asyncio.run(client.call(model=None, system="s", user="u", images=[str(img_path)]))

    user_msg = captured["body"]["messages"][1]
    assert len(user_msg["images"]) == 1
    decoded = base64.b64decode(user_msg["images"][0])
    assert decoded == b"\x89PNG\r\nfake"


def test_call_non_200_raises(cfg):
    async def fake_post(url, json=None):
        return _mock_response({"error": "model not found"}, status=404)

    with _patch_client(AsyncMock(side_effect=fake_post)):
        client = LocalLLMClient(cfg)
        with pytest.raises(LocalLLMError):
            asyncio.run(client.call(model="m", system="s", user="u"))


def test_call_connect_error_raises_local_error(cfg):
    async def fake_post(url, json=None):
        raise httpx.ConnectError("nope")

    with _patch_client(AsyncMock(side_effect=fake_post)):
        client = LocalLLMClient(cfg)
        with pytest.raises(LocalLLMError):
            asyncio.run(client.call(model="m", system="s", user="u"))


def test_warmup_ok(cfg):
    async def fake_post(url, json=None):
        return _mock_response({"response": ""}, status=200)

    with _patch_client(AsyncMock(side_effect=fake_post)):
        client = LocalLLMClient(cfg)
        ok = asyncio.run(client.warmup("m1"))
        assert ok is True


def test_warmup_failure_returns_false(cfg):
    async def fake_post(url, json=None):
        raise httpx.ConnectError("nope")

    with _patch_client(AsyncMock(side_effect=fake_post)):
        client = LocalLLMClient(cfg)
        ok = asyncio.run(client.warmup("m1"))
        assert ok is False
