"""Tool registry keyed by name. Agents only get tools on their allow-list.

Enforcement is belt + suspenders:
  1. specs_for_allowlist() — only allow-listed tools are ever sent to the
     model, so it cannot request anything else through the API.
  2. run_tool() re-checks the allow-list before executing, so even a bug in
     (1) or a crafted history cannot execute an off-list tool.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.tools.base import Tool, ToolNotAllowedError, ToolNotFoundError
from app.tools.builtin import BUILTIN_TOOLS
from app.tools.memory import MEMORY_TOOL_NAMES, MEMORY_TOOLS
from app.tools.quill import QUILL_TOOLS

log = logging.getLogger("agentcloud.tools")

REGISTRY: dict[str, Tool] = {
    t.name: t for t in (*BUILTIN_TOOLS, *QUILL_TOOLS, *MEMORY_TOOLS)
}


def specs_for_allowlist(allowlist: list[str]) -> list[dict[str, Any]]:
    specs = []
    for name in allowlist:
        tool = REGISTRY.get(name)
        if tool is None:
            log.warning("agent allow-list references unknown tool %r — skipped", name)
            continue
        specs.append(tool.spec())
    return specs


async def run_tool(name: str, args: dict[str, Any], allowlist: list[str]) -> str:
    if name not in allowlist:
        raise ToolNotAllowedError(f"tool {name!r} is not on this agent's allow-list")
    tool = REGISTRY.get(name)
    if tool is None:
        raise ToolNotFoundError(name)
    try:
        return await tool.handler(args or {})
    except Exception as exc:  # noqa: BLE001 — tool errors go back to the model
        log.exception("tool %s failed", name)
        return json.dumps({"error": f"tool {name} failed: {exc}"})


__all__ = [
    "MEMORY_TOOL_NAMES",
    "REGISTRY",
    "Tool",
    "ToolNotAllowedError",
    "ToolNotFoundError",
    "run_tool",
    "specs_for_allowlist",
]
