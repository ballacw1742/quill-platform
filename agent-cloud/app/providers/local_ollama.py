"""Local-inference ModelProvider (MODEL_PROVIDER=local).

§9.5 realization: "inference on local hardware, pay only for electricity."
The orchestrator is provider-agnostic (drives a generic tool loop over the
`ModelProvider` contract in app/providers/base.py), so a local engine is a
one-file add + a `get_provider` branch.

Primary engine: **ollama** — the most portable option. We speak ollama's
*native* HTTP API (`/api/chat`, `/api/embed`) rather than its OpenAI-compat
`/v1` shim because the native surface is stable across ollama's model
backends (llama.cpp *and* MLX), whereas the `/v1` shim requires the bundled
`llama-server` binary that some installs (e.g. Homebrew MLX-only setups)
lack. Native `/api/chat` returns `prompt_eval_count` (input) and `eval_count`
(output) token accounting directly.

The engine is factored behind `LocalEngine` so vLLM / llama.cpp adapters can
be added later behind the same `MODEL_PROVIDER=local` selection without
touching the orchestrator or the provider contract. `OLLAMA_HOST` selects the
base URL; `LOCAL_ENGINE` selects the adapter (only "ollama" today).

Contract mapping (Anthropic-style ⇄ ollama native):
  * tools:   {name, description, input_schema}
             → {"type": "function", "function": {name, description,
                                                  parameters: input_schema}}
  * messages: assistant content is a list of Anthropic blocks
              (text / tool_use); user content is either a plain string or a
              list of tool_result blocks. We flatten to ollama's role/content
              (+ tool_calls / role="tool") wire shape.
  * output:  normalized back to Anthropic blocks
             ({"type":"text","text":...} / {"type":"tool_use","id","name",
             "input"}) so ModelResponse.tool_uses / .text work unchanged.
  * stop_reason: "tool_use" when the model emitted tool calls, else
             "end_turn" (mirrors the Anthropic provider so the orchestrator's
             `resp.stop_reason != "tool_use"` branch is correct).
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import get_settings
from app.providers.base import (
    ModelProvider,
    ModelResponse,
    ProviderError,
    StreamEvent,
    with_retries,
)

log = logging.getLogger("agentcloud.providers.local")


# The lane router / pricing layer tags on-prem model ids with a provider
# prefix ('ollama:' / 'local:') so cost accounting can pin them to $0
# (pricing.ZERO_COST_PREFIXES). ollama's own API wants the bare engine model
# name, so we strip a single leading routing prefix before every call. A bare
# 'local' (the canonical zero-cost id) has no engine model and is rejected
# with an actionable error rather than silently guessing.
_ROUTING_PREFIXES = ("ollama:", "local:")


def _engine_model(model: str) -> str:
    m = (model or "").strip()
    low = m.lower()
    for pfx in _ROUTING_PREFIXES:
        if low.startswith(pfx):
            return m[len(pfx):]
    if low == "local":
        raise ProviderError(
            "local provider requires a concrete engine model id "
            "(e.g. 'ollama:qwen3:14b' or 'qwen3:14b'), not the bare 'local' "
            "alias; set the agent's model or MODEL_LOCAL_DEFAULT"
        )
    return m


# --------------------------------------------------------------------------
# retry classification (mirrors embeddings._is_retryable_http)
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# Anthropic-style ⇄ ollama-native wire translation (engine-agnostic)
# --------------------------------------------------------------------------
def _tools_to_ollama(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anthropic tools[] → ollama function-tools[]."""
    out: list[dict[str, Any]] = []
    for t in tools:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema")
                    or {"type": "object", "properties": {}},
                },
            }
        )
    return out


def _stringify(content: Any) -> str:
    """tool_result content may be a str or a list of blocks; ollama's
    role='tool' wants a plain string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for b in content:
            if isinstance(b, dict):
                parts.append(b.get("text", "") if b.get("type") == "text" else json.dumps(b))
            else:
                parts.append(str(b))
        return "".join(parts)
    return json.dumps(content)


def _messages_to_ollama(
    system: str, messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Flatten Anthropic system+messages into ollama's role/content list.

    Assistant blocks split into content text + tool_calls; user tool_result
    blocks become individual role="tool" messages (ollama's convention)."""
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})

    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")

        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        # content is a list of Anthropic blocks
        if role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for b in content:
                btype = b.get("type")
                if btype == "text":
                    text_parts.append(b.get("text", ""))
                elif btype == "tool_use":
                    tool_calls.append(
                        {
                            "function": {
                                "name": b.get("name", ""),
                                "arguments": b.get("input") or {},
                            }
                        }
                    )
            msg: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts)}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            out.append(msg)
        else:
            # user turn carrying tool_result block(s)
            emitted = False
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    out.append(
                        {
                            "role": "tool",
                            "content": _stringify(b.get("content", "")),
                        }
                    )
                    emitted = True
            if not emitted:
                out.append({"role": role, "content": _stringify(content)})
    return out


def _normalize_message(msg: dict[str, Any], model: str, done_reason: str | None,
                       input_tokens: int, output_tokens: int) -> ModelResponse:
    """ollama message dict → Anthropic-style ModelResponse."""
    blocks: list[dict[str, Any]] = []
    text = msg.get("content") or ""
    if text:
        blocks.append({"type": "text", "text": text})

    tool_calls = msg.get("tool_calls") or []
    for i, tc in enumerate(tool_calls):
        fn = tc.get("function", {})
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (ValueError, TypeError):
                args = {"_raw": args}
        blocks.append(
            {
                "type": "tool_use",
                "id": tc.get("id") or f"call_{i}",
                "name": fn.get("name", ""),
                "input": args or {},
            }
        )

    stop_reason = "tool_use" if tool_calls else "end_turn"
    return ModelResponse(
        content=blocks,
        stop_reason=stop_reason,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


# --------------------------------------------------------------------------
# engine abstraction (ollama today; vLLM/llama.cpp later behind this)
# --------------------------------------------------------------------------
class LocalEngine:
    """Base for local inference engines behind MODEL_PROVIDER=local."""

    name = "base"


class OllamaEngine(LocalEngine):
    """ollama native-API engine (http://localhost:11434 by default)."""

    name = "ollama"

    def __init__(self, *, base_url: str, timeout: float,
                 client: httpx.AsyncClient | None = None):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client  # injectable for tests

    def _http(self) -> httpx.AsyncClient:
        # When a client is injected (tests), reuse it; otherwise per-call
        # client so we never leak a session across the event loop.
        return self._client or httpx.AsyncClient(timeout=self._timeout)

    async def _post(self, path: str, body: dict[str, Any]) -> httpx.Response:
        if self._client is not None:
            r = await self._client.post(f"{self._base_url}{path}", json=body)
            r.raise_for_status()
            return r
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(f"{self._base_url}{path}", json=body)
            r.raise_for_status()
            return r

    async def chat(self, body: dict[str, Any]) -> dict[str, Any]:
        r = await self._post("/api/chat", body)
        return r.json()

    async def chat_stream(self, body: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """Yield each NDJSON object from ollama's streaming /api/chat."""
        if self._client is not None:
            async with self._client.stream(
                "POST", f"{self._base_url}/api/chat", json=body
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.strip():
                        yield json.loads(line)
            return
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST", f"{self._base_url}/api/chat", json=body
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.strip():
                        yield json.loads(line)


# --------------------------------------------------------------------------
# the provider
# --------------------------------------------------------------------------
class LocalProvider(ModelProvider):
    """MODEL_PROVIDER=local — inference on local hardware (ollama)."""

    name = "local"

    def __init__(self, engine: LocalEngine | None = None):
        s = get_settings()
        self._settings = s
        if engine is not None:
            self._engine: LocalEngine = engine
        else:
            eng = (s.LOCAL_ENGINE or "ollama").strip().lower()
            if eng != "ollama":
                raise ProviderError(
                    f"unknown LOCAL_ENGINE '{eng}' (only 'ollama' is implemented; "
                    "vLLM/llama.cpp adapters can be added behind LocalEngine)"
                )
            self._engine = OllamaEngine(
                base_url=s.OLLAMA_HOST,
                timeout=s.LOCAL_INFERENCE_TIMEOUT_SECONDS,
            )

    def _base_body(
        self, model: str, system: str, messages: list[dict[str, Any]],
        tools: list[dict[str, Any]], max_tokens: int,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": _engine_model(model),
            "messages": _messages_to_ollama(system, messages),
            # Disable "thinking" traces: they aren't part of the ModelResponse
            # contract and would pollute the reply text. Harmless on models
            # that don't support it.
            "think": False,
            "options": {"num_predict": max_tokens},
        }
        if tools:
            body["tools"] = _tools_to_ollama(tools)
        return body

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
        body = self._base_body(model, system, messages, tools, max_tokens)
        body["stream"] = False

        async def _call() -> ModelResponse:
            data = await self._engine.chat(body)
            return _normalize_message(
                data.get("message", {}) or {},
                data.get("model", model),
                data.get("done_reason"),
                int(data.get("prompt_eval_count", 0) or 0),
                int(data.get("eval_count", 0) or 0),
            )

        try:
            return await with_retries(
                _call,
                attempts=s.MODEL_RETRY_ATTEMPTS,
                base_delay=s.MODEL_RETRY_BASE_DELAY,
                is_retryable=_is_retryable_http,
                what=f"local.complete({model})",
            )
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"local ollama API error {exc.response.status_code}: "
                f"{exc.response.text[:300]}",
                status=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"local ollama request failed (is ollama running at "
                f"{s.OLLAMA_HOST}?): {exc}"
            ) from exc
        except (KeyError, ValueError) as exc:
            raise ProviderError(f"local ollama response malformed: {exc}") from exc

    def stream(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> AsyncIterator[StreamEvent]:
        s = self._settings
        body = self._base_body(model, system, messages, tools, max_tokens)
        body["stream"] = True

        async def _gen() -> AsyncIterator[StreamEvent]:
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            final_model = model
            done_reason: str | None = None
            input_tokens = 0
            output_tokens = 0
            try:
                async for chunk in self._engine.chat_stream(body):
                    msg = chunk.get("message") or {}
                    delta = msg.get("content") or ""
                    if delta:
                        text_parts.append(delta)
                        yield StreamEvent(type="text_delta", text=delta)
                    if msg.get("tool_calls"):
                        tool_calls.extend(msg["tool_calls"])
                    if chunk.get("done"):
                        final_model = chunk.get("model", model)
                        done_reason = chunk.get("done_reason")
                        input_tokens = int(chunk.get("prompt_eval_count", 0) or 0)
                        output_tokens = int(chunk.get("eval_count", 0) or 0)
            except httpx.HTTPStatusError as exc:
                raise ProviderError(
                    f"local ollama stream error {exc.response.status_code}: "
                    f"{exc.response.text[:300]}",
                    status=exc.response.status_code,
                ) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(
                    f"local ollama stream request failed (is ollama running at "
                    f"{s.OLLAMA_HOST}?): {exc}"
                ) from exc

            final_msg: dict[str, Any] = {"content": "".join(text_parts)}
            if tool_calls:
                final_msg["tool_calls"] = tool_calls
            resp = _normalize_message(
                final_msg, final_model, done_reason, input_tokens, output_tokens
            )
            yield StreamEvent(type="final", response=resp)

        return _gen()


__all__ = ["LocalProvider", "OllamaEngine", "LocalEngine"]
