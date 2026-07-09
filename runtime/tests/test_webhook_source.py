"""Tests for WebhookEventSource (§9 Wave 2, prod ingress).

Tests use the asyncio.Queue injection path (_queue parameter) to avoid
binding real sockets in unit tests.  A separate set of integration tests
starts the server and makes real HTTP requests.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import threading
import time
import pytest

from runtime.triage_dispatcher import (
    TriageEvent,
    WebhookEventSource,
    build_default_source,
    MockDataEventSource,
    InMemoryEventSource,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(kind: str = "rfi.new", summary: str = "test") -> dict:
    return {
        "kind": kind,
        "status": "submitted",
        "approval_id": f"appr-{kind}-1",
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Queue-injection (no socket) tests
# ---------------------------------------------------------------------------

async def test_webhook_source_yields_from_queue():
    """Events put into the queue are yielded by __aiter__."""
    q: asyncio.Queue = asyncio.Queue()
    stop = asyncio.Event()
    source = WebhookEventSource(port=0, secret="", stop_event=stop, _queue=q)

    record = _make_record("rfi.new", "A question about concrete")
    await q.put(record)
    # Signal stop after putting the event
    stop.set()

    events = []
    async for ev in source:
        events.append(ev)

    assert len(events) == 1
    assert events[0].kind == "rfi.new"


async def test_webhook_source_skips_non_dispatchable():
    """Records with status=error are skipped (from_log_record returns None)."""
    q: asyncio.Queue = asyncio.Queue()
    stop = asyncio.Event()
    source = WebhookEventSource(port=0, secret="", stop_event=stop, _queue=q)

    bad_record = {"kind": "rfi.new", "status": "error", "approval_id": "x"}
    await q.put(bad_record)
    stop.set()

    events = []
    async for ev in source:
        events.append(ev)

    assert len(events) == 0


async def test_webhook_source_skips_non_dict():
    """Non-dict queue items are skipped without raising."""
    q: asyncio.Queue = asyncio.Queue()
    stop = asyncio.Event()
    source = WebhookEventSource(port=0, secret="", stop_event=stop, _queue=q)

    await q.put("not a dict")
    stop.set()

    events = []
    async for ev in source:
        events.append(ev)

    assert len(events) == 0


async def test_webhook_source_multiple_events():
    """Multiple events from the queue all get yielded."""
    q: asyncio.Queue = asyncio.Queue()
    stop = asyncio.Event()
    source = WebhookEventSource(port=0, secret="", stop_event=stop, _queue=q)

    for i in range(3):
        await q.put(_make_record("rfi.new", f"summary {i}"))
    stop.set()

    events = []
    async for ev in source:
        events.append(ev)

    assert len(events) == 3


# ---------------------------------------------------------------------------
# build_default_source factory
# ---------------------------------------------------------------------------

def test_build_webhook_source():
    src = build_default_source(source_type="webhook", webhook_port=9999, webhook_secret="s3cr3t")
    assert isinstance(src, WebhookEventSource)
    assert src.port == 9999
    assert src._secret == "s3cr3t"


def test_build_file_source(tmp_path):
    log = tmp_path / "dispatch.log"
    src = build_default_source(source_type="file", log_path=log)
    assert isinstance(src, MockDataEventSource)


def test_build_mock_source(tmp_path):
    """'mock' is accepted as an alias for 'file'."""
    log = tmp_path / "dispatch.log"
    src = build_default_source(source_type="mock", log_path=log)
    assert isinstance(src, MockDataEventSource)


def test_build_unknown_source():
    with pytest.raises(ValueError, match="unknown event source"):
        build_default_source(source_type="unknown")


# ---------------------------------------------------------------------------
# HTTP integration tests (real server, ephemeral port)
# ---------------------------------------------------------------------------

def _post_events(port: int, events: list[dict], secret: str = "") -> tuple[int, dict]:
    """Synchronous helper to POST /events to the webhook server."""
    body = json.dumps({"events": events}).encode()
    conn = http.client.HTTPConnection("localhost", port, timeout=5)
    headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
    if secret:
        headers["X-Triage-Secret"] = secret
    conn.request("POST", "/events", body=body, headers=headers)
    resp = conn.getresponse()
    status = resp.status
    data = json.loads(resp.read())
    conn.close()
    return status, data


def _find_free_port() -> int:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


async def test_http_server_accepts_events_no_secret():
    """Server with no secret configured accepts any request."""
    port = _find_free_port()
    source = WebhookEventSource(port=port, secret="")
    await source.start()

    try:
        record = _make_record("rfi.new", "HTTP integration test")
        status, body = _post_events(port, [record])
        assert status == 200
        assert body.get("ok") is True

        # Check the event arrived in the queue
        raw = await asyncio.wait_for(source._queue.get(), timeout=2.0)
        assert raw["kind"] == "rfi.new"
    finally:
        source.stop()


async def test_http_server_rejects_wrong_secret():
    """Server with secret configured rejects requests with wrong/missing secret."""
    port = _find_free_port()
    source = WebhookEventSource(port=port, secret="correct-secret")
    await source.start()

    try:
        record = _make_record("rfi.new", "Should be rejected")
        # No secret
        status, _ = _post_events(port, [record], secret="")
        assert status == 401

        # Wrong secret
        status, _ = _post_events(port, [record], secret="wrong")
        assert status == 401

        # Queue should be empty
        assert source._queue.empty()
    finally:
        source.stop()


async def test_http_server_accepts_correct_secret():
    """Server with secret configured accepts requests with the correct secret."""
    port = _find_free_port()
    source = WebhookEventSource(port=port, secret="my-secret")
    await source.start()

    try:
        record = _make_record("rfi.new", "Auth test")
        status, body = _post_events(port, [record], secret="my-secret")
        assert status == 200
        assert body.get("ok") is True

        raw = await asyncio.wait_for(source._queue.get(), timeout=2.0)
        assert raw["kind"] == "rfi.new"
    finally:
        source.stop()


async def test_http_server_rejects_invalid_json():
    """Server returns 400 for malformed JSON body."""
    port = _find_free_port()
    source = WebhookEventSource(port=port, secret="")
    await source.start()

    try:
        conn = http.client.HTTPConnection("localhost", port, timeout=5)
        body = b"not json at all"
        conn.request(
            "POST", "/events", body=body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(body))}
        )
        resp = conn.getresponse()
        assert resp.status == 400
        conn.close()
    finally:
        source.stop()


async def test_http_server_rejects_missing_events_key():
    """Server returns 400 when body has no 'events' key."""
    port = _find_free_port()
    source = WebhookEventSource(port=port, secret="")
    await source.start()

    try:
        status, _ = _post_events(port, None)  # type: ignore[arg-type]
    except Exception:
        pass
    # Manually craft bad body
    conn = http.client.HTTPConnection("localhost", port, timeout=5)
    bad_body = json.dumps({"data": []}).encode()
    conn.request(
        "POST", "/events", body=bad_body,
        headers={"Content-Type": "application/json", "Content-Length": str(len(bad_body))}
    )
    resp = conn.getresponse()
    assert resp.status == 400
    conn.close()
    source.stop()


async def test_http_server_rejects_unknown_path():
    """Unknown paths return 404."""
    port = _find_free_port()
    source = WebhookEventSource(port=port, secret="")
    await source.start()

    try:
        conn = http.client.HTTPConnection("localhost", port, timeout=5)
        conn.request("POST", "/unknown", body=b"{}", headers={"Content-Length": "2"})
        resp = conn.getresponse()
        assert resp.status == 404
        conn.close()
    finally:
        source.stop()
