"""Tests for quill_bot.transcription (Phase F.2 — Commit 1).

Network calls are mocked at the httpx transport layer so these tests are
fully offline and deterministic.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from quill_bot.transcription import (
    DEFAULT_BASE_URL,
    TranscriptionAPIError,
    TranscriptionNotConfigured,
    TranscriptionResult,
    TranscriptionTooLarge,
    WHISPER_MAX_BYTES,
    WhisperClient,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
VERBOSE_JSON_OK = {
    "task": "transcribe",
    "language": "english",
    "duration": 2.7,
    "text": "What's pending today?",
    "segments": [
        {
            "id": 0,
            "start": 0.0,
            "end": 2.7,
            "text": "What's pending today?",
        }
    ],
}


class _MockTransport(httpx.AsyncBaseTransport):
    """httpx async transport that returns scripted responses.

    Each entry in `script` is either:
      - a dict with shape {"status": int, "json": Any} → JSON response
      - a dict with shape {"status": int, "text": str}
      - an Exception → raised as a transport error
    The transport also records every request it saw under `.requests`.
    """

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        # Read content so we can assert on it later.
        await request.aread()
        self.requests.append(request)
        if not self._script:
            raise AssertionError("transport called more times than scripted")
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        if "json" in item:
            return httpx.Response(
                status_code=item["status"],
                content=json.dumps(item["json"]).encode("utf-8"),
                headers={"content-type": "application/json"},
            )
        return httpx.Response(
            status_code=item["status"],
            content=item.get("text", "").encode("utf-8"),
            headers={"content-type": "text/plain"},
        )


@pytest.fixture
def patched_async_client(monkeypatch: pytest.MonkeyPatch):
    """Patch httpx.AsyncClient so WhisperClient uses our scripted transport.

    Returns a function that takes a script and returns the transport, so
    tests can assert on the recorded requests after the call.
    """
    transport_holder: dict[str, _MockTransport] = {}

    real_async_client = httpx.AsyncClient

    def _factory(script: list[Any]) -> _MockTransport:
        transport = _MockTransport(script)
        transport_holder["t"] = transport

        def _patched(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
            kwargs["transport"] = transport
            return real_async_client(*args, **kwargs)

        monkeypatch.setattr("quill_bot.transcription.httpx.AsyncClient", _patched)
        return transport

    return _factory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestIsAvailable:
    def test_no_key_unavailable(self) -> None:
        assert WhisperClient(api_key=None).is_available is False
        assert WhisperClient(api_key="").is_available is False
        assert WhisperClient(api_key="   ").is_available is False

    def test_valid_key_available(self) -> None:
        assert WhisperClient(api_key="sk-test").is_available is True


@pytest.mark.asyncio
async def test_transcribe_not_configured_raises() -> None:
    client = WhisperClient(api_key=None)
    with pytest.raises(TranscriptionNotConfigured) as exc_info:
        await client.transcribe(b"fake-audio")
    assert exc_info.value.code == "not_configured"


@pytest.mark.asyncio
async def test_transcribe_success_path(patched_async_client) -> None:
    transport = patched_async_client([{"status": 200, "json": VERBOSE_JSON_OK}])
    client = WhisperClient(api_key="sk-test")

    result = await client.transcribe(b"\x00\x01\x02fake-ogg-bytes")

    assert isinstance(result, TranscriptionResult)
    assert result.text == "What's pending today?"
    assert result.duration_sec == pytest.approx(2.7)
    assert result.language == "english"
    assert result.confidence is None
    assert result.tokens_consumed is None

    # Verify the request shape.
    assert len(transport.requests) == 1
    req = transport.requests[0]
    assert req.method == "POST"
    assert req.url.path == "/v1/audio/transcriptions"
    assert req.headers.get("authorization") == "Bearer sk-test"
    body = req.content
    assert b"whisper-1" in body
    assert b"verbose_json" in body
    assert b"fake-ogg-bytes" in body


@pytest.mark.asyncio
async def test_transcribe_retries_on_5xx(patched_async_client) -> None:
    transport = patched_async_client(
        [
            {"status": 502, "text": "bad gateway"},
            {"status": 200, "json": VERBOSE_JSON_OK},
        ]
    )
    # Patch sleep so retry backoffs don't slow tests.
    import quill_bot.transcription as t_mod

    sleeps: list[float] = []

    async def _fake_sleep(d: float) -> None:
        sleeps.append(d)

    original = t_mod.asyncio.sleep
    t_mod.asyncio.sleep = _fake_sleep  # type: ignore[assignment]
    try:
        client = WhisperClient(api_key="sk-test")
        result = await client.transcribe(b"audio")
    finally:
        t_mod.asyncio.sleep = original  # type: ignore[assignment]

    assert result.text == "What's pending today?"
    assert len(transport.requests) == 2
    assert sleeps == [1.0]  # first backoff


@pytest.mark.asyncio
async def test_transcribe_retries_on_transport_error(
    patched_async_client,
) -> None:
    transport = patched_async_client(
        [
            httpx.ConnectError("kaboom"),
            {"status": 200, "json": VERBOSE_JSON_OK},
        ]
    )
    import quill_bot.transcription as t_mod

    async def _fake_sleep(d: float) -> None:
        return None

    original = t_mod.asyncio.sleep
    t_mod.asyncio.sleep = _fake_sleep  # type: ignore[assignment]
    try:
        client = WhisperClient(api_key="sk-test")
        result = await client.transcribe(b"audio")
    finally:
        t_mod.asyncio.sleep = original  # type: ignore[assignment]

    assert result.text == "What's pending today?"
    # Both attempts recorded: the first raised (still recorded by the transport),
    # the second returned 200.
    assert len(transport.requests) == 2


@pytest.mark.asyncio
async def test_transcribe_4xx_does_not_retry(patched_async_client) -> None:
    transport = patched_async_client(
        [{"status": 401, "text": "invalid api key"}]
    )
    client = WhisperClient(api_key="sk-bad")
    with pytest.raises(TranscriptionAPIError) as exc_info:
        await client.transcribe(b"audio")
    assert exc_info.value.status == 401
    assert "invalid api key" in exc_info.value.body
    # Critically: only ONE request — no retries on auth errors.
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_transcribe_5xx_exhausts_retries(patched_async_client) -> None:
    transport = patched_async_client(
        [
            {"status": 500, "text": "boom"},
            {"status": 503, "text": "down"},
            {"status": 502, "text": "bad gateway"},
        ]
    )
    import quill_bot.transcription as t_mod

    async def _fake_sleep(d: float) -> None:
        return None

    original = t_mod.asyncio.sleep
    t_mod.asyncio.sleep = _fake_sleep  # type: ignore[assignment]
    try:
        client = WhisperClient(api_key="sk-test")
        with pytest.raises(TranscriptionAPIError) as exc_info:
            await client.transcribe(b"audio")
    finally:
        t_mod.asyncio.sleep = original  # type: ignore[assignment]

    assert exc_info.value.status == 502  # last response surfaced
    assert len(transport.requests) == 3  # initial + 2 retries


@pytest.mark.asyncio
async def test_transcribe_too_large() -> None:
    client = WhisperClient(api_key="sk-test")
    huge = b"\x00" * (WHISPER_MAX_BYTES + 1)
    with pytest.raises(TranscriptionTooLarge) as exc_info:
        await client.transcribe(huge)
    assert exc_info.value.size == WHISPER_MAX_BYTES + 1


@pytest.mark.asyncio
async def test_transcribe_accepts_bytearray(patched_async_client) -> None:
    patched_async_client([{"status": 200, "json": VERBOSE_JSON_OK}])
    client = WhisperClient(api_key="sk-test")
    result = await client.transcribe(bytearray(b"audio-bytes"))
    assert result.text == "What's pending today?"


@pytest.mark.asyncio
async def test_transcribe_accepts_path(tmp_path, patched_async_client) -> None:
    audio_path = tmp_path / "voice.ogg"
    audio_path.write_bytes(b"file-on-disk")
    transport = patched_async_client([{"status": 200, "json": VERBOSE_JSON_OK}])
    client = WhisperClient(api_key="sk-test")
    result = await client.transcribe(audio_path)
    assert result.text == "What's pending today?"
    assert b"file-on-disk" in transport.requests[0].content


def test_default_base_url_is_openai() -> None:
    # Just a sanity check that we point at the right host by default —
    # cheap insurance against accidental rebases.
    assert DEFAULT_BASE_URL == "https://api.openai.com/v1"
