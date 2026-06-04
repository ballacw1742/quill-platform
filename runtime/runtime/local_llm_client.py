"""Ollama-backed local LLM client (Gemma 4 12B and friends).

Implements the same `LLMResponse` contract as `llm_client.LLMClient` so
`agent.py` and downstream code remain backend-agnostic. See
`MODEL_ROUTING_CONTRACT.md` §3 for the interface contract.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

# Pin exception classes at import time. Some downstream code paths in tests
# can monkey-patch the httpx module and we want our except clauses to keep
# matching real network errors regardless.
_HttpxConnectError = httpx.ConnectError
_HttpxTimeoutException = httpx.TimeoutException

log = structlog.get_logger(__name__)


@dataclass
class LocalLLMConfig:
    base_url: str = "http://localhost:11434"
    default_model: str = "gemma4:12b-mlx"
    timeout_s: float = 120.0

    @classmethod
    def from_env(cls) -> "LocalLLMConfig":
        return cls(
            base_url=os.environ.get("LOCAL_INFERENCE_URL", "http://localhost:11434").rstrip("/"),
            default_model=os.environ.get("LOCAL_MODEL_NAME", "gemma4:12b-mlx"),
            timeout_s=float(os.environ.get("LOCAL_TIMEOUT_S", "120")),
        )


class LocalLLMError(RuntimeError):
    """Local backend failed (connection refused, model not loaded, timeout)."""


class LocalLLMClient:
    """Thin Ollama /api/chat client.

    Ollama's /api/chat accepts a `messages` array (system + user) and a
    `format: "json"` hint which forces structured output. We use it because
    every Quill agent contract requires JSON.
    """

    def __init__(self, cfg: LocalLLMConfig | None = None) -> None:
        self.cfg = cfg or LocalLLMConfig.from_env()

    async def call(
        self,
        *,
        model: str | None,
        system: str,
        user: str,
        images: list[str] | None = None,
        temperature: float = 0.0,
        timeout_s: float | None = None,
        format_json: bool = True,
    ) -> dict[str, Any]:
        """Make a single chat completion request. Returns a dict with:

        - text: str (the assistant message)
        - model_used: str
        - input_tokens: int
        - output_tokens: int
        - latency_ms: int

        ``images`` is an optional list of either local file paths or base64-
        encoded image bytes. Ollama's /api/chat accepts a parallel ``images``
        list on the user message. Used by the multimodal path (Sprint Gemma.2).
        """
        model = model or self.cfg.default_model
        timeout = timeout_s if timeout_s is not None else self.cfg.timeout_s
        url = f"{self.cfg.base_url}/api/chat"

        user_msg: dict[str, Any] = {"role": "user", "content": user}
        if images:
            user_msg["images"] = [self._encode_image(i) for i in images]

        payload: dict[str, Any] = {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                user_msg,
            ],
            "options": {
                "temperature": float(temperature),
            },
        }
        if format_json:
            payload["format"] = "json"
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload)
        except _HttpxConnectError as e:
            raise LocalLLMError(f"could not reach Ollama at {self.cfg.base_url}: {e}") from e
        except _HttpxTimeoutException as e:
            raise LocalLLMError(f"local call timed out after {timeout}s: {e}") from e

        latency_ms = int((time.perf_counter() - start) * 1000)

        if resp.status_code != 200:
            raise LocalLLMError(
                f"ollama returned {resp.status_code}: {resp.text[:300]}"
            )

        try:
            body = resp.json()
        except json.JSONDecodeError as e:
            raise LocalLLMError(f"ollama returned non-JSON envelope: {e}") from e

        msg = body.get("message") or {}
        text = (msg.get("content") or "").strip()

        # Ollama returns prompt_eval_count / eval_count as best-effort token counts.
        in_tok = int(body.get("prompt_eval_count") or 0)
        out_tok = int(body.get("eval_count") or 0)

        log.info(
            "local_llm.call.ok",
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=latency_ms,
            text_len=len(text),
        )

        return {
            "text": text,
            "model_used": model,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "latency_ms": latency_ms,
        }

    @staticmethod
    def _encode_image(src: str) -> str:
        """Accept either a base64 string (already encoded) or a filesystem path.

        Heuristic: anything that's a readable file gets read + b64-encoded;
        anything else is assumed to be a base64 string already.
        """
        import base64
        import os.path

        if os.path.isfile(src):
            with open(src, "rb") as fh:
                return base64.b64encode(fh.read()).decode("ascii")
        return src

    async def stream(
        self,
        *,
        model: str | None,
        system: str,
        user: str,
        images: list[str] | None = None,
        temperature: float = 0.0,
        format_json: bool = False,
        timeout_s: float | None = None,
    ):
        """Async generator yielding text deltas as Ollama streams them.

        Used by Sprint Gemma.3 real-time agent loops. Each yield is a str
        containing the next chunk of the assistant message. The final yield
        is an empty string when ``done=True`` arrives, after which the
        generator returns.

        Note: ``format_json`` defaults to False here because JSON-mode and
        streaming compose awkwardly (you can't render half a JSON object).
        Callers that need streaming + JSON should buffer and validate after.
        """
        model = model or self.cfg.default_model
        timeout = timeout_s if timeout_s is not None else self.cfg.timeout_s
        url = f"{self.cfg.base_url}/api/chat"

        user_msg: dict[str, Any] = {"role": "user", "content": user}
        if images:
            user_msg["images"] = [self._encode_image(i) for i in images]

        payload: dict[str, Any] = {
            "model": model,
            "stream": True,
            "messages": [
                {"role": "system", "content": system},
                user_msg,
            ],
            "options": {"temperature": float(temperature)},
        }
        if format_json:
            payload["format"] = "json"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        raise LocalLLMError(
                            f"ollama stream returned {resp.status_code}: {body[:300]!r}"
                        )
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            evt = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        msg = evt.get("message") or {}
                        chunk = msg.get("content") or ""
                        if chunk:
                            yield chunk
                        if evt.get("done"):
                            return
        except _HttpxConnectError as e:
            raise LocalLLMError(f"could not reach Ollama at {self.cfg.base_url}: {e}") from e
        except _HttpxTimeoutException as e:
            raise LocalLLMError(f"local stream timed out: {e}") from e

    async def warmup(self, model: str | None = None) -> bool:
        """Keep-alive ping. Issues a no-op generate that forces Ollama to load
        the model into memory. Returns True on success, False on failure.
        Used by the keep-alive daemon to avoid the 15-20s cold-start latency.
        """
        model = model or self.cfg.default_model
        url = f"{self.cfg.base_url}/api/generate"
        payload = {
            "model": model,
            "prompt": "",
            "keep_alive": "30m",
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self.cfg.timeout_s) as client:
                resp = await client.post(url, json=payload)
            ok = resp.status_code == 200
            log.info("local_llm.warmup", model=model, ok=ok)
            return ok
        except (_HttpxConnectError, _HttpxTimeoutException) as e:
            log.warning("local_llm.warmup.fail", model=model, err=str(e))
            return False


__all__ = ["LocalLLMClient", "LocalLLMConfig", "LocalLLMError"]
