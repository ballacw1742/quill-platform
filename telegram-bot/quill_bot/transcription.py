"""WhisperClient — OpenAI audio transcription wrapper (Phase F.2).

Thin async client around OpenAI's `/audio/transcriptions` endpoint. We use
this to turn Telegram voice notes into text the existing NL handler can
consume. Implementation choices:

- httpx directly, no `openai` SDK — matches the rest of the bot's HTTP
  patterns and keeps deps lean.
- `response_format=verbose_json` so we get duration + detected language
  alongside the transcript text.
- Retries: 2 attempts with 1s + 4s backoff on 5xx or transport errors.
  4xx (auth, file-too-big, malformed) raise immediately — retrying won't
  help and we want fast user feedback.
- Telegram voice messages arrive as .ogg/Opus and Whisper accepts that
  format natively, so no transcoding is needed.

Usage:

    client = WhisperClient(api_key=os.environ.get("OPENAI_API_KEY"))
    if not client.is_available:
        ...graceful refusal...
    result = await client.transcribe(ogg_bytes)
    text = result.text
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("quill.bot.transcription")


# 25 MB Whisper API hard cap (also Telegram's voice upload cap in practice).
WHISPER_MAX_BYTES = 25 * 1024 * 1024
DEFAULT_MODEL = "whisper-1"
DEFAULT_LANGUAGE = "en"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_TIMEOUT_SECONDS = 30.0
RETRY_BACKOFFS = (1.0, 4.0)  # seconds; len == max retries


# ---------------------------------------------------------------------------
# Result + error types
# ---------------------------------------------------------------------------
@dataclass
class TranscriptionResult:
    """Outcome of a single Whisper call.

    `confidence` is None because Whisper-1 does not return per-utterance
    confidence in its public API; we keep the field so future models can
    populate it without a contract change. `tokens_consumed` is also None
    today (audio API doesn't bill in tokens) — kept for symmetry with
    other LLM-call tracking.
    """

    text: str
    duration_sec: float
    language: str
    confidence: float | None = None
    tokens_consumed: int | None = None


class TranscriptionError(Exception):
    """Base class for transcription failures."""


class TranscriptionNotConfigured(TranscriptionError):
    """Raised when the client was constructed without an API key.

    The voice handler treats this as a graceful refusal — Charles is told
    that voice notes need an OpenAI API key on the server.
    """

    def __init__(self, msg: str = "OPENAI_API_KEY not configured") -> None:
        super().__init__(msg)
        self.code = "not_configured"


class TranscriptionAPIError(TranscriptionError):
    """4xx/5xx response from OpenAI we couldn't recover from."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"whisper api error status={status} body={body[:200]}")
        self.status = status
        self.body = body


class TranscriptionTooLarge(TranscriptionError):
    """Audio payload exceeds Whisper's 25 MB cap."""

    def __init__(self, size: int) -> None:
        super().__init__(
            f"audio payload {size} bytes exceeds {WHISPER_MAX_BYTES} byte cap"
        )
        self.size = size


# ---------------------------------------------------------------------------
# WhisperClient
# ---------------------------------------------------------------------------
class WhisperClient:
    def __init__(
        self,
        api_key: str | None,
        *,
        model: str = DEFAULT_MODEL,
        language: str = DEFAULT_LANGUAGE,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = (api_key or "").strip() or None
        self.model = model
        self.language = language
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @property
    def is_available(self) -> bool:
        """True iff an API key is configured. The voice handler checks
        this before attempting any download or upload to give the user
        an instant, no-network response when the bot is misconfigured."""
        return self._api_key is not None

    # ------------------------------------------------------------------
    async def transcribe(
        self,
        audio: bytes | bytearray | memoryview | Path,
        *,
        mime_type: str = "audio/ogg",
        filename: str = "voice.ogg",
    ) -> TranscriptionResult:
        """Transcribe audio bytes (or a Path to a file) via Whisper.

        Returns a TranscriptionResult on success. Raises:
          * TranscriptionNotConfigured — no API key on this client
          * TranscriptionTooLarge — payload > 25 MB
          * TranscriptionAPIError — non-recoverable HTTP error from OpenAI
          * httpx.HTTPError — only after all retries are exhausted
        """
        if not self.is_available:
            raise TranscriptionNotConfigured()

        data = _coerce_to_bytes(audio)
        if len(data) > WHISPER_MAX_BYTES:
            raise TranscriptionTooLarge(len(data))

        url = f"{self.base_url}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        files = {"file": (filename, data, mime_type)}
        form: dict[str, str] = {
            "model": self.model,
            "response_format": "verbose_json",
        }
        if self.language:
            form["language"] = self.language

        last_exc: Exception | None = None
        attempts = len(RETRY_BACKOFFS) + 1  # initial + retries
        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        url, headers=headers, data=form, files=files
                    )
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last_exc = e
                log.warning(
                    "whisper.transport_error attempt=%d/%d err=%s",
                    attempt + 1,
                    attempts,
                    e,
                )
                if attempt < attempts - 1:
                    await asyncio.sleep(RETRY_BACKOFFS[attempt])
                    continue
                raise

            if resp.status_code == 200:
                return _parse_verbose_json(resp.json())

            # 4xx → fail fast, retrying won't help.
            if 400 <= resp.status_code < 500:
                body = _safe_text(resp)
                log.warning(
                    "whisper.client_error status=%d body=%s",
                    resp.status_code,
                    body[:200],
                )
                raise TranscriptionAPIError(resp.status_code, body)

            # 5xx → retry with backoff.
            body = _safe_text(resp)
            log.warning(
                "whisper.server_error status=%d attempt=%d/%d body=%s",
                resp.status_code,
                attempt + 1,
                attempts,
                body[:200],
            )
            last_exc = TranscriptionAPIError(resp.status_code, body)
            if attempt < attempts - 1:
                await asyncio.sleep(RETRY_BACKOFFS[attempt])
                continue
            assert last_exc is not None
            raise last_exc

        # Unreachable, but mypy-friendly.
        if last_exc is not None:
            raise last_exc
        raise TranscriptionError("transcribe: exhausted attempts with no result")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _coerce_to_bytes(audio: bytes | bytearray | memoryview | Path) -> bytes:
    if isinstance(audio, Path):
        return audio.read_bytes()
    if isinstance(audio, (bytes, bytearray, memoryview)):
        return bytes(audio)
    raise TypeError(f"unsupported audio type: {type(audio)!r}")


def _safe_text(resp: httpx.Response) -> str:
    try:
        return resp.text
    except Exception:  # noqa: BLE001
        return ""


def _parse_verbose_json(payload: dict[str, Any]) -> TranscriptionResult:
    """Coerce a `verbose_json` response into a TranscriptionResult.

    Whisper-1 returns:
        {
          "task": "transcribe",
          "language": "english",
          "duration": 3.2,
          "text": "...",
          "segments": [...]
        }
    """
    text = str(payload.get("text", "") or "")
    duration = payload.get("duration")
    try:
        duration_sec = float(duration) if duration is not None else 0.0
    except (TypeError, ValueError):
        duration_sec = 0.0
    language = str(payload.get("language") or DEFAULT_LANGUAGE)
    return TranscriptionResult(
        text=text,
        duration_sec=duration_sec,
        language=language,
        confidence=None,
        tokens_consumed=None,
    )


__all__ = [
    "WhisperClient",
    "TranscriptionResult",
    "TranscriptionError",
    "TranscriptionNotConfigured",
    "TranscriptionAPIError",
    "TranscriptionTooLarge",
    "WHISPER_MAX_BYTES",
]
