"""Anthropic-on-Vertex provider (config-gated: MODEL_PROVIDER=vertex).

Status (see agent-cloud/SPIKE_FINDINGS.md): Claude models are listed for
project totemic-formula-467102-s9 on the *global* endpoint only, but
`global_online_prediction_requests_per_base_model` quota is effectively 0
and every rawPredict returns 429. Quota increase requests were filed
2026-07-06 and are pending. Until granted, this provider fails **cleanly**
with an actionable ProviderError; cutover is flipping MODEL_PROVIDER=vertex.

Auth is IAM (service account / ADC) — no API key, per design doc §6.
"""

from __future__ import annotations

import logging
from typing import Any

import anthropic

from app.config import get_settings
from app.providers.anthropic_direct import _is_retryable, _normalize
from app.providers.base import ModelProvider, ModelResponse, ProviderError, with_retries

log = logging.getLogger("agentcloud.providers.vertex")

_QUOTA_HINT = (
    "Vertex Claude quota is pending for this project "
    "(global_online_prediction_requests_per_base_model = 0; increase filed "
    "2026-07-06). Set MODEL_PROVIDER=anthropic until the increase lands."
)


class VertexAnthropicProvider(ModelProvider):
    name = "vertex"

    def __init__(self, client: anthropic.AsyncAnthropicVertex | None = None):
        self._settings = get_settings()
        if client is not None:
            self._client = client
        else:
            try:
                self._client = anthropic.AsyncAnthropicVertex(
                    project_id=self._settings.VERTEX_PROJECT,
                    region=self._settings.VERTEX_REGION,
                    max_retries=0,
                )
            except Exception as exc:  # bad ADC / missing deps
                raise ProviderError(f"vertex provider init failed: {exc}") from exc

    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> ModelResponse:
        s = self._settings

        async def _call() -> ModelResponse:
            msg = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                tools=tools,
                messages=messages,
            )
            return _normalize(msg)

        try:
            return await with_retries(
                _call,
                attempts=s.MODEL_RETRY_ATTEMPTS,
                base_delay=s.MODEL_RETRY_BASE_DELAY,
                is_retryable=_is_retryable,
                what=f"vertex.complete({model})",
            )
        except anthropic.APIStatusError as exc:
            hint = f" {_QUOTA_HINT}" if exc.status_code == 429 else ""
            raise ProviderError(
                f"vertex API error {exc.status_code}: {exc.message}.{hint}",
                status=exc.status_code,
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(f"vertex connection error: {exc}") from exc
