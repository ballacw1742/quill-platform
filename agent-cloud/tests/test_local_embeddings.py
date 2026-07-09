"""Local embeddings (EMBEDDING_PROVIDER=local, ollama /api/embed) — mock-only.

Also asserts the existing 'none' fallback still raises the documented error
so memory's text-search degradation path is unchanged.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import get_settings
from app.providers.embeddings import (
    EmbeddingUnavailableError,
    LocalEmbeddingProvider,
    get_embedding_provider,
)


def _dim() -> int:
    return get_settings().EMBEDDING_DIM


async def test_local_embeddings_parses_vectors():
    dim = _dim()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embed"
        import json

        body = json.loads(request.content)
        n = len(body["input"])
        return httpx.Response(200, json={"embeddings": [[0.1] * dim for _ in range(n)]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    prov = LocalEmbeddingProvider(client=client)
    vecs = await prov.embed(["a", "b"])
    assert len(vecs) == 2
    assert all(len(v) == dim for v in vecs)
    await client.aclose()


async def test_local_embeddings_dim_mismatch_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3]]})  # wrong dim

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    prov = LocalEmbeddingProvider(client=client)
    with pytest.raises(EmbeddingUnavailableError) as e:
        await prov.embed(["x"])
    assert "dimension" in str(e.value).lower()
    await client.aclose()


async def test_local_embeddings_http_error_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    prov = LocalEmbeddingProvider(client=client)
    with pytest.raises(EmbeddingUnavailableError):
        await prov.embed(["x"])
    await client.aclose()


def test_factory_selects_local_embeddings(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    try:
        prov = get_embedding_provider()
        assert prov.name == "local"
        assert isinstance(prov, LocalEmbeddingProvider)
    finally:
        get_settings.cache_clear()


def test_none_fallback_still_raises():
    prov_err = None
    try:
        get_embedding_provider("none")
    except EmbeddingUnavailableError as e:
        prov_err = e
    assert prov_err is not None
    assert "none" in str(prov_err)


def test_unknown_embedding_provider_rejected():
    with pytest.raises(EmbeddingUnavailableError) as e:
        get_embedding_provider("word2vec")
    assert "word2vec" in str(e.value)
