"""Embedding providers for the memory subsystem.

Same config-gated selection pattern as MODEL_PROVIDER (app/providers):

  EMBEDDING_PROVIDER=gemini  — Gemini API direct (GEMINI_API_KEY). The
      pragmatic live path today: Vertex online-prediction quota for this
      project is effectively 0 (SPIKE_FINDINGS.md), and the design doc's
      "Gemini for embeddings" is reachable via the Gemini API key path
      without any quota filing.
  EMBEDDING_PROVIDER=vertex  — IAM-auth'd Vertex text embeddings; config-
      gated, clean named error if credentials/quota are missing.
  EMBEDDING_PROVIDER=none    — embeddings off; memory degrades to text
      search (memory_search ILIKE fallback).

All failures raise EmbeddingUnavailableError with a clean, named message —
callers (app/memory.py) catch it and fall back rather than breaking a turn.
"""

from __future__ import annotations

import abc
import logging
from typing import Any

import httpx

from app.config import get_settings
from app.providers.base import with_retries

log = logging.getLogger("agentcloud.providers.embeddings")

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class EmbeddingUnavailableError(RuntimeError):
    """Embeddings cannot be produced right now (config/auth/quota/network)."""


class EmbeddingProvider(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one EMBEDDING_DIM-length vector per input text."""


def _check_dims(vectors: list[list[float]], expected: int, who: str) -> list[list[float]]:
    for v in vectors:
        if len(v) != expected:
            raise EmbeddingUnavailableError(
                f"{who} returned dimension {len(v)}, expected EMBEDDING_DIM={expected}"
            )
    return vectors


def _is_retryable_http(exc: Exception) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (
        429,
        500,
        502,
        503,
    ):
        return True
    return False


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Gemini API direct (models/<model>:batchEmbedContents, key auth)."""

    name = "gemini"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        s = get_settings()
        if not s.GEMINI_API_KEY:
            raise EmbeddingUnavailableError(
                "EMBEDDING_PROVIDER=gemini but GEMINI_API_KEY is not configured"
            )
        body = {
            "requests": [
                {
                    "model": f"models/{s.EMBEDDING_MODEL}",
                    "content": {"parts": [{"text": t}]},
                    "outputDimensionality": s.EMBEDDING_DIM,
                }
                for t in texts
            ]
        }

        async def _call() -> list[list[float]]:
            async with httpx.AsyncClient(timeout=s.EMBEDDING_TIMEOUT_SECONDS) as client:
                r = await client.post(
                    f"{GEMINI_API_BASE}/models/{s.EMBEDDING_MODEL}:batchEmbedContents",
                    params={"key": s.GEMINI_API_KEY},
                    json=body,
                )
                r.raise_for_status()
                data = r.json()
            return [e["values"] for e in data["embeddings"]]

        try:
            vectors = await with_retries(
                _call,
                attempts=s.MODEL_RETRY_ATTEMPTS,
                base_delay=s.MODEL_RETRY_BASE_DELAY,
                is_retryable=_is_retryable_http,
                what=f"gemini.embed({s.EMBEDDING_MODEL})",
            )
        except httpx.HTTPStatusError as exc:
            raise EmbeddingUnavailableError(
                f"gemini embeddings API error {exc.response.status_code}: "
                f"{exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise EmbeddingUnavailableError(f"gemini embeddings request failed: {exc}") from exc
        except (KeyError, ValueError) as exc:
            raise EmbeddingUnavailableError(
                f"gemini embeddings response malformed: {exc}"
            ) from exc
        return _check_dims(vectors, s.EMBEDDING_DIM, "gemini embeddings")


class VertexEmbeddingProvider(EmbeddingProvider):
    """Vertex AI text embeddings (IAM auth). Config-gated; fails cleanly."""

    name = "vertex"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        s = get_settings()
        try:
            import google.auth  # noqa: PLC0415
            import google.auth.transport.requests  # noqa: PLC0415

            creds, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            creds.refresh(google.auth.transport.requests.Request())
            token = creds.token
        except Exception as exc:  # noqa: BLE001 — normalize to the named error
            raise EmbeddingUnavailableError(
                f"vertex embeddings: could not obtain IAM credentials: {exc}"
            ) from exc

        region = s.VERTEX_REGION
        host = (
            "aiplatform.googleapis.com"
            if region == "global"
            else f"{region}-aiplatform.googleapis.com"
        )
        url = (
            f"https://{host}/v1/projects/{s.VERTEX_PROJECT}/locations/{region}"
            f"/publishers/google/models/{s.EMBEDDING_MODEL}:predict"
        )
        body: dict[str, Any] = {
            "instances": [{"content": t} for t in texts],
            "parameters": {"outputDimensionality": s.EMBEDDING_DIM},
        }

        async def _call() -> list[list[float]]:
            async with httpx.AsyncClient(timeout=s.EMBEDDING_TIMEOUT_SECONDS) as client:
                r = await client.post(
                    url, json=body, headers={"Authorization": f"Bearer {token}"}
                )
                r.raise_for_status()
                data = r.json()
            return [p["embeddings"]["values"] for p in data["predictions"]]

        try:
            vectors = await with_retries(
                _call,
                attempts=s.MODEL_RETRY_ATTEMPTS,
                base_delay=s.MODEL_RETRY_BASE_DELAY,
                is_retryable=_is_retryable_http,
                what=f"vertex.embed({s.EMBEDDING_MODEL})",
            )
        except httpx.HTTPStatusError as exc:
            hint = ""
            if exc.response.status_code == 429:
                hint = " (Vertex quota — see SPIKE_FINDINGS.md; use EMBEDDING_PROVIDER=gemini)"
            raise EmbeddingUnavailableError(
                f"vertex embeddings API error {exc.response.status_code}{hint}: "
                f"{exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise EmbeddingUnavailableError(f"vertex embeddings request failed: {exc}") from exc
        except (KeyError, ValueError) as exc:
            raise EmbeddingUnavailableError(
                f"vertex embeddings response malformed: {exc}"
            ) from exc
        return _check_dims(vectors, s.EMBEDDING_DIM, "vertex embeddings")


def get_embedding_provider(name: str | None = None) -> EmbeddingProvider:
    provider = (name or get_settings().EMBEDDING_PROVIDER).strip().lower()
    if provider == "gemini":
        return GeminiEmbeddingProvider()
    if provider == "vertex":
        return VertexEmbeddingProvider()
    if provider in ("none", ""):
        raise EmbeddingUnavailableError(
            "EMBEDDING_PROVIDER=none — embeddings disabled by config"
        )
    raise EmbeddingUnavailableError(
        f"unknown EMBEDDING_PROVIDER '{provider}' (expected 'gemini', 'vertex', or 'none')"
    )


__all__ = [
    "EmbeddingProvider",
    "EmbeddingUnavailableError",
    "GeminiEmbeddingProvider",
    "VertexEmbeddingProvider",
    "get_embedding_provider",
]
