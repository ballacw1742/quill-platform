"""Model providers. Switch with MODEL_PROVIDER=anthropic|vertex|local."""

from __future__ import annotations

from app.config import get_settings
from app.providers.base import ModelProvider, ModelResponse, ProviderError, StreamEvent


def get_provider(name: str | None = None) -> ModelProvider:
    provider = (name or get_settings().MODEL_PROVIDER).strip().lower()
    if provider == "anthropic":
        from app.providers.anthropic_direct import AnthropicDirectProvider

        return AnthropicDirectProvider()
    if provider == "vertex":
        from app.providers.vertex_anthropic import VertexAnthropicProvider

        return VertexAnthropicProvider()
    if provider == "local":
        from app.providers.local_ollama import LocalProvider

        return LocalProvider()
    raise ProviderError(
        f"unknown MODEL_PROVIDER '{provider}' "
        "(expected 'anthropic', 'vertex', or 'local')"
    )


__all__ = [
    "ModelProvider",
    "ModelResponse",
    "ProviderError",
    "StreamEvent",
    "get_provider",
]
