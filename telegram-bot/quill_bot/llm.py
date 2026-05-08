"""ConversationalLLM — the multi-turn tool-use loop (Phase B, Commit 4).

Wraps the Anthropic SDK to:

  1. Send the user's message + recent history + tool definitions to Claude.
  2. If Claude returns stop_reason == 'tool_use', execute every tool_use
     block via TOOL_REGISTRY, stitch the results back into the message
     stream, and call Claude again.
  3. Repeat until stop_reason != 'tool_use' or we hit MAX_ITERATIONS.
  4. Return the final assistant text + the cumulative tool-call log.

Prompt caching: the system prompt + tool definitions are marked with
`cache_control: ephemeral` on the first turn so subsequent turns hit the
Anthropic prompt cache.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quill_bot.conversation import Message
from quill_bot.tools import (
    TOOL_REGISTRY,
    ChatContext,
    anthropic_tool_specs,
    execute_tool,
)

log = logging.getLogger("quill.bot.llm")


DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_ITERATIONS = 6
DEFAULT_MAX_TOKENS = 1024


def _load_system_prompt() -> str:
    here = Path(__file__).parent
    p = here / "prompts" / "conversation_system.md"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    # Defensive fallback — prompt file should always exist.
    return "You are Quill, a project assistant. Be brief and accurate."


SYSTEM_PROMPT = _load_system_prompt()


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------
@dataclass
class ToolCallRecord:
    name: str
    input: dict[str, Any]
    result: dict[str, Any]
    tool_use_id: str
    iteration: int


@dataclass
class AssistantTurn:
    text: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    iterations: int = 0
    stop_reason: str = ""
    latency_ms: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    # Each iteration's assistant content_blocks (so the handler can persist
    # tool_use blocks alongside assistant text).
    assistant_blocks: list[list[dict[str, Any]]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ConversationalLLM
# ---------------------------------------------------------------------------
class ConversationalLLM:
    def __init__(
        self,
        client: Any,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_iterations: int = MAX_ITERATIONS,
    ) -> None:
        self.client = client
        self.model = model or os.environ.get("BOT_LLM_MODEL", DEFAULT_MODEL)
        self.system_prompt = system_prompt or SYSTEM_PROMPT
        self.tools = tools if tools is not None else anthropic_tool_specs()
        self.max_tokens = max_tokens
        self.max_iterations = max_iterations

    # ------------------------------------------------------------------
    def _system_blocks(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "text",
                "text": self.system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def _tools_with_cache(self) -> list[dict[str, Any]]:
        # Mark the LAST tool definition with cache_control so the entire
        # tool block is part of the cache prefix. Anthropic caches the
        # everything-up-to-and-including the cache_control marker.
        if not self.tools:
            return []
        out = [dict(t) for t in self.tools]
        out[-1] = {**out[-1], "cache_control": {"type": "ephemeral"}}
        return out

    def _trim(self, history: list[Message], max_messages: int) -> list[Message]:
        """Keep the most recent N messages, but always start the surviving
        slice on a 'user' role boundary. Anthropic requires alternation
        starting with user; if we slice mid-tool_use→tool_result pair we'll
        get a 400.
        """
        if len(history) <= max_messages:
            return list(history)
        sliced = history[-max_messages:]
        # Walk forward until we land on a user-role message.
        while sliced and sliced[0].to_anthropic()["role"] != "user":
            sliced.pop(0)
        return sliced

    # ------------------------------------------------------------------
    async def turn(
        self,
        user_text: str,
        history: list[Message],
        ctx: ChatContext,
        *,
        max_history: int = 24,
    ) -> AssistantTurn:
        """Run one logical turn: user_text + history → final assistant text."""
        start = time.monotonic()

        trimmed = self._trim(history, max_history)
        # Build the message stream Anthropic sees on this turn.
        messages: list[dict[str, Any]] = [m.to_anthropic() for m in trimmed]
        messages.append({"role": "user", "content": user_text})

        result = AssistantTurn(text="")
        cum_usage: dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }

        for iteration in range(1, self.max_iterations + 1):
            result.iterations = iteration
            try:
                resp = await self._call_claude(messages)
            except Exception as e:  # noqa: BLE001
                log.exception("anthropic_call_failed")
                result.text = f"⚠️ I hit an error talking to the LLM: {e}"
                result.stop_reason = "error"
                break

            stop_reason = getattr(resp, "stop_reason", None) or "end_turn"
            content_blocks = _content_to_dicts(getattr(resp, "content", []))
            result.assistant_blocks.append(content_blocks)
            result.stop_reason = stop_reason

            # Roll up usage if available.
            usage = getattr(resp, "usage", None)
            if usage is not None:
                for k in cum_usage:
                    v = getattr(usage, k, None)
                    if isinstance(v, int):
                        cum_usage[k] += v

            if stop_reason != "tool_use":
                # Final answer — concatenate any text blocks.
                result.text = "".join(
                    b.get("text", "") for b in content_blocks if b.get("type") == "text"
                ).strip()
                break

            # Otherwise: execute every tool_use in the content, append the
            # assistant's tool_use block + a user-role tool_result block.
            messages.append({"role": "assistant", "content": content_blocks})

            tool_results: list[dict[str, Any]] = []
            for blk in content_blocks:
                if blk.get("type") != "tool_use":
                    continue
                tool_name = blk["name"]
                tool_input = blk.get("input", {}) or {}
                tool_use_id = blk["id"]
                exec_result = await execute_tool(tool_name, tool_input, ctx)
                result.tool_calls.append(
                    ToolCallRecord(
                        name=tool_name,
                        input=tool_input,
                        result=exec_result,
                        tool_use_id=tool_use_id,
                        iteration=iteration,
                    )
                )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": json.dumps(exec_result, default=str),
                    }
                )

            if not tool_results:
                # Defensive: stop_reason said tool_use but no tool blocks?
                result.text = "".join(
                    b.get("text", "") for b in content_blocks if b.get("type") == "text"
                ).strip()
                break
            messages.append({"role": "user", "content": tool_results})
        else:
            # Loop fell through MAX_ITERATIONS without an end_turn.
            log.warning("llm.max_iterations_hit", extra={"chat_id": ctx.chat_id})
            if not result.text:
                # Best-effort: pick up the last assistant text.
                if result.assistant_blocks:
                    result.text = "".join(
                        b.get("text", "")
                        for b in result.assistant_blocks[-1]
                        if b.get("type") == "text"
                    ).strip()
            if not result.text:
                result.text = (
                    "⚠️ I hit my tool-call limit before settling on an answer. "
                    "Try asking again with a simpler ask."
                )
            result.stop_reason = "max_iterations"

        result.latency_ms = int((time.monotonic() - start) * 1000)
        result.usage = cum_usage
        log.info(
            "llm.turn_complete",
            extra={
                "iterations": result.iterations,
                "stop_reason": result.stop_reason,
                "latency_ms": result.latency_ms,
                "tool_calls": len(result.tool_calls),
                "input_tokens": cum_usage["input_tokens"],
                "output_tokens": cum_usage["output_tokens"],
                "cache_read": cum_usage["cache_read_input_tokens"],
                "cache_create": cum_usage["cache_creation_input_tokens"],
            },
        )
        return result

    # ------------------------------------------------------------------
    async def _call_claude(self, messages: list[dict[str, Any]]) -> Any:
        """One round-trip to Anthropic. Async if possible, threaded otherwise."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": self._system_blocks(),
            "messages": messages,
            "tools": self._tools_with_cache(),
        }
        create = self.client.messages.create  # type: ignore[attr-defined]
        if asyncio.iscoroutinefunction(create):
            return await create(**kwargs)
        # Sync SDK — push to a thread.
        return await asyncio.to_thread(create, **kwargs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _content_to_dicts(content: Any) -> list[dict[str, Any]]:
    """Normalise Anthropic SDK content blocks (objects or dicts) to dicts."""
    out: list[dict[str, Any]] = []
    for blk in content or []:
        if isinstance(blk, dict):
            out.append(blk)
            continue
        # SDK object — pull common attributes.
        d: dict[str, Any] = {}
        btype = getattr(blk, "type", None)
        if btype:
            d["type"] = btype
        if btype == "text":
            d["text"] = getattr(blk, "text", "")
        elif btype == "tool_use":
            d["id"] = getattr(blk, "id", "")
            d["name"] = getattr(blk, "name", "")
            d["input"] = getattr(blk, "input", {}) or {}
        else:
            # Fallback — best-effort dictify
            for k in ("id", "name", "input", "text", "content"):
                v = getattr(blk, k, None)
                if v is not None:
                    d[k] = v
        out.append(d)
    return out


__all__ = [
    "AssistantTurn",
    "ConversationalLLM",
    "MAX_ITERATIONS",
    "DEFAULT_MODEL",
    "SYSTEM_PROMPT",
    "ToolCallRecord",
]
