"""Tests for quill_web_fetch read tool (§9 Wave 2, MIGRATION.md §3.3)."""

from __future__ import annotations

import json
import os
import pytest

from app.tools import REGISTRY, run_tool
from app.tools.web_tools import (
    WEB_TOOL_NAMES,
    WEB_TOOLS,
    _WEB_FETCH_MAX_CHARS_CEILING,
    _WEB_FETCH_PER_TURN_LIMIT,
    _reset_turn_count,
    quill_web_fetch,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _MockHttpxResponse:
    def __init__(self, status_code: int = 200, text: str = "<html>Hello</html>"):
        self.status_code = status_code
        self.text = text


class _MockHttpxClient:
    """Capture GET calls without network."""

    def __init__(self, response: _MockHttpxResponse | None = None, raise_exc=None):
        self._response = response or _MockHttpxResponse()
        self._raise_exc = raise_exc
        self.requests: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, url: str, **kwargs):
        self.requests.append({"url": url, **kwargs})
        if self._raise_exc:
            raise self._raise_exc
        return self._response


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_web_fetch_in_registry():
    assert "quill_web_fetch" in REGISTRY


def test_web_tool_names():
    assert "quill_web_fetch" in WEB_TOOL_NAMES


def test_web_tools_list():
    names = [t.name for t in WEB_TOOLS]
    assert "quill_web_fetch" in names


# ---------------------------------------------------------------------------
# Feature gate (ALLOW_WEB_FETCH)
# ---------------------------------------------------------------------------

async def test_web_fetch_disabled_by_default():
    """Without ALLOW_WEB_FETCH=true the tool returns a disabled error."""
    from app.config import get_settings
    # Ensure default setting (false)
    get_settings.cache_clear()
    os.environ.pop("ALLOW_WEB_FETCH", None)
    try:
        result_json = await quill_web_fetch.handler({"url": "https://example.com"})
        result = json.loads(result_json)
        assert "error" in result
        assert "ALLOW_WEB_FETCH" in result["error"]
    finally:
        get_settings.cache_clear()


async def test_web_fetch_enabled(monkeypatch):
    """With ALLOW_WEB_FETCH=true the tool attempts the fetch."""
    monkeypatch.setenv("ALLOW_WEB_FETCH", "true")
    from app.config import get_settings
    get_settings.cache_clear()
    _reset_turn_count()

    mock_client = _MockHttpxClient(_MockHttpxResponse(200, "<html>test</html>"))
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    try:
        result_json = await quill_web_fetch.handler({"url": "https://example.com"})
        result = json.loads(result_json)
        assert result["status_code"] == 200
        assert "test" in result["body"]
    finally:
        get_settings.cache_clear()
        _reset_turn_count()


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

async def test_web_fetch_rejects_http_url(monkeypatch):
    monkeypatch.setenv("ALLOW_WEB_FETCH", "true")
    from app.config import get_settings
    get_settings.cache_clear()
    _reset_turn_count()
    try:
        result_json = await quill_web_fetch.handler({"url": "http://example.com"})
        result = json.loads(result_json)
        assert "error" in result
        assert "https" in result["error"]
    finally:
        get_settings.cache_clear()
        _reset_turn_count()


async def test_web_fetch_rejects_empty_url(monkeypatch):
    monkeypatch.setenv("ALLOW_WEB_FETCH", "true")
    from app.config import get_settings
    get_settings.cache_clear()
    _reset_turn_count()
    try:
        result_json = await quill_web_fetch.handler({"url": ""})
        result = json.loads(result_json)
        assert "error" in result
        assert "url" in result["error"].lower()
    finally:
        get_settings.cache_clear()
        _reset_turn_count()


async def test_web_fetch_max_chars_clamped(monkeypatch):
    """max_chars above the ceiling is silently clamped."""
    monkeypatch.setenv("ALLOW_WEB_FETCH", "true")
    from app.config import get_settings
    get_settings.cache_clear()
    _reset_turn_count()

    long_body = "x" * 100_000
    mock_client = _MockHttpxClient(_MockHttpxResponse(200, long_body))
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    try:
        result_json = await quill_web_fetch.handler({
            "url": "https://example.com",
            "max_chars": 999_999,  # way above ceiling
        })
        result = json.loads(result_json)
        assert len(result["body"]) <= _WEB_FETCH_MAX_CHARS_CEILING
        assert result["truncated"] is True
    finally:
        get_settings.cache_clear()
        _reset_turn_count()


async def test_web_fetch_returns_truncated_flag(monkeypatch):
    """truncated=True when body exceeds max_chars."""
    monkeypatch.setenv("ALLOW_WEB_FETCH", "true")
    from app.config import get_settings
    get_settings.cache_clear()
    _reset_turn_count()

    long_body = "a" * 5000
    mock_client = _MockHttpxClient(_MockHttpxResponse(200, long_body))
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    try:
        result_json = await quill_web_fetch.handler({
            "url": "https://example.com",
            "max_chars": 100,
        })
        result = json.loads(result_json)
        assert result["truncated"] is True
        assert len(result["body"]) == 100
    finally:
        get_settings.cache_clear()
        _reset_turn_count()


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

async def test_web_fetch_rate_limit(monkeypatch):
    """After _WEB_FETCH_PER_TURN_LIMIT calls, the tool returns a rate-limit error."""
    monkeypatch.setenv("ALLOW_WEB_FETCH", "true")
    from app.config import get_settings
    get_settings.cache_clear()
    _reset_turn_count()

    mock_client = _MockHttpxClient(_MockHttpxResponse(200, "ok"))
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    try:
        # Exhaust the limit
        for _ in range(_WEB_FETCH_PER_TURN_LIMIT):
            result_json = await quill_web_fetch.handler({"url": "https://example.com"})
            result = json.loads(result_json)
            assert "error" not in result, f"Unexpected error before limit: {result}"

        # Next call should be rate-limited
        result_json = await quill_web_fetch.handler({"url": "https://example.com"})
        result = json.loads(result_json)
        assert "error" in result
        assert "rate limit" in result["error"].lower()
    finally:
        get_settings.cache_clear()
        _reset_turn_count()


async def test_web_fetch_rate_limit_resets_after_reset(monkeypatch):
    """After _reset_turn_count(), calls are permitted again."""
    monkeypatch.setenv("ALLOW_WEB_FETCH", "true")
    from app.config import get_settings
    get_settings.cache_clear()
    _reset_turn_count()

    mock_client = _MockHttpxClient(_MockHttpxResponse(200, "ok"))
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    try:
        # Exhaust
        for _ in range(_WEB_FETCH_PER_TURN_LIMIT):
            await quill_web_fetch.handler({"url": "https://example.com"})

        # Reset (simulates a new turn)
        _reset_turn_count()

        result_json = await quill_web_fetch.handler({"url": "https://example.com"})
        result = json.loads(result_json)
        assert "error" not in result
    finally:
        get_settings.cache_clear()
        _reset_turn_count()


# ---------------------------------------------------------------------------
# HTTP error handling
# ---------------------------------------------------------------------------

async def test_web_fetch_handles_http_error(monkeypatch):
    """httpx.HTTPError is caught and returned as a tool error."""
    monkeypatch.setenv("ALLOW_WEB_FETCH", "true")
    from app.config import get_settings
    get_settings.cache_clear()
    _reset_turn_count()

    import httpx
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _MockHttpxClient(raise_exc=httpx.ConnectError("connection refused")),
    )

    try:
        result_json = await quill_web_fetch.handler({"url": "https://example.com"})
        result = json.loads(result_json)
        assert "error" in result
        assert "HTTP" in result["error"] or "connection" in result["error"].lower()
    finally:
        get_settings.cache_clear()
        _reset_turn_count()


# ---------------------------------------------------------------------------
# Agent Builder catalog
# ---------------------------------------------------------------------------

def test_web_tool_in_catalog():
    """quill_web_fetch appears in the tool catalog under the 'web' group."""
    from app import agents as agents_mod
    catalog = agents_mod.tool_catalog()
    web_group = next(
        (g for g in catalog["groups"] if g["group"] == "web"), None
    )
    assert web_group is not None
    names = [t["name"] for t in web_group["tools"]]
    assert "quill_web_fetch" in names


def test_web_tool_not_approval_gated():
    """quill_web_fetch is a read-only tool — not approval-gated."""
    from app import agents as agents_mod
    catalog = agents_mod.tool_catalog()
    for group in catalog["groups"]:
        for tool in group["tools"]:
            if tool["name"] == "quill_web_fetch":
                assert tool["approval_gated"] is False
                return
    pytest.fail("quill_web_fetch not found in catalog")
