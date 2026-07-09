"""Web fetch read tool (§9 Wave 2, MIGRATION.md §3.3).

Read-only, no approval gate.  Gated behind ALLOW_WEB_FETCH=true (default
false).  Rate-limited to 5 calls per agent turn using a ContextVar so the
counter is naturally scoped to a single asyncio task (each HTTP request / job
run creates a new task context).

Security rationale: this tool allows an agent to reach *any* https:// URL.
It is deliberately off by default so a fresh deployment does not expose
unexpected outbound reach.  An operator must set ALLOW_WEB_FETCH=true to
enable it.

Rate limit: the ContextVar resets to 0 for every new asyncio task, which maps
1:1 to a chat turn or a subagent job run.  Within a turn, after 5 calls the
tool returns an error instead of making further requests.
"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from typing import Any

import httpx

from app.config import get_settings
from app.tools.base import Tool

log = logging.getLogger("agentcloud.tools.web")

_WEB_FETCH_MAX_CHARS_CEILING = 20_000
_WEB_FETCH_DEFAULT_CHARS = 8_000
_WEB_FETCH_PER_TURN_LIMIT = 5

# Per-turn call counter.  Default 0; each new asyncio task starts with its
# own copy (Python contextvar semantics), so this correctly resets between
# chat turns and subagent jobs without any explicit reset mechanism.
_turn_web_fetch_count: ContextVar[int] = ContextVar("turn_web_fetch_count", default=0)


def _reset_turn_count() -> None:
    """Reset the per-turn counter.  Test hook — call before exercising the
    rate limit in unit tests that run in the same task."""
    _turn_web_fetch_count.set(0)


async def _web_fetch_handler(args: dict[str, Any]) -> str:
    s = get_settings()

    # Feature gate.
    if not s.ALLOW_WEB_FETCH:
        return json.dumps(
            {
                "error": (
                    "quill_web_fetch is disabled; set ALLOW_WEB_FETCH=true to enable it"
                )
            }
        )

    # Rate limit (per turn / per asyncio task).
    count = _turn_web_fetch_count.get()
    if count >= _WEB_FETCH_PER_TURN_LIMIT:
        return json.dumps(
            {
                "error": (
                    f"rate limit: quill_web_fetch may be called at most "
                    f"{_WEB_FETCH_PER_TURN_LIMIT} times per agent turn"
                )
            }
        )
    _turn_web_fetch_count.set(count + 1)

    # Input validation.
    url = (args.get("url") or "").strip()
    if not url:
        return json.dumps({"error": "url is required"})
    if not url.startswith("https://"):
        return json.dumps({"error": "url must begin with https:// (http:// is not allowed)"})

    max_chars = args.get("max_chars", _WEB_FETCH_DEFAULT_CHARS)
    try:
        max_chars = int(max_chars)
    except (TypeError, ValueError):
        return json.dumps({"error": "max_chars must be an integer"})
    if max_chars <= 0:
        return json.dumps({"error": "max_chars must be greater than 0"})
    max_chars = min(max_chars, _WEB_FETCH_MAX_CHARS_CEILING)

    # Fetch.
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "quill-agent/1.0"})
    except httpx.HTTPError as exc:
        log.warning("web_fetch GET failed: %s %s", url, exc)
        return json.dumps({"error": f"HTTP request failed: {exc}"})

    body = r.text[:max_chars]
    return json.dumps(
        {
            "url": url,
            "status_code": r.status_code,
            "chars_returned": len(body),
            "truncated": len(r.text) > max_chars,
            "body": body,
        }
    )


quill_web_fetch = Tool(
    name="quill_web_fetch",
    description=(
        "Fetch the contents of an https:// URL and return the first "
        f"{_WEB_FETCH_DEFAULT_CHARS} chars of the response body (configurable "
        f"up to {_WEB_FETCH_MAX_CHARS_CEILING}).  Read-only; no data is written.  "
        "Requires ALLOW_WEB_FETCH=true to be configured.  "
        f"Rate-limited to {_WEB_FETCH_PER_TURN_LIMIT} calls per agent turn."
    ),
    handler=_web_fetch_handler,
    input_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The https:// URL to fetch.",
            },
            "max_chars": {
                "type": "integer",
                "description": (
                    f"Maximum characters to return from the response body "
                    f"(default {_WEB_FETCH_DEFAULT_CHARS}, "
                    f"max {_WEB_FETCH_MAX_CHARS_CEILING})."
                ),
            },
        },
        "required": ["url"],
    },
)

WEB_TOOLS = [quill_web_fetch]
WEB_TOOL_NAMES = [t.name for t in WEB_TOOLS]
