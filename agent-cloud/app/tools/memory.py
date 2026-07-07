"""Memory tools: memory_save + memory_search.

The (tenant, agent) namespace comes from the request contextvars set by the
orchestrator at turn start (app/logging_setup.py) — the model cannot pick a
namespace, so a crafted prompt can't read or write another tenant's (or
another agent's) memory. RLS underneath is the second belt.

Availability is governed twice: the agent's tool allow-list (like every
tool) AND the agent's memory_policy — the orchestrator strips these tools
from the effective allow-list when memory_policy='off'.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app import memory as memory_mod
from app.logging_setup import agent_id_var, tenant_id_var
from app.tools.base import Tool

log = logging.getLogger("agentcloud.tools.memory")


def _namespace() -> tuple[str, str] | None:
    tenant_id = tenant_id_var.get()
    agent_id = agent_id_var.get()
    if not tenant_id or not agent_id:
        return None
    return tenant_id, agent_id


async def _memory_save(args: dict[str, Any]) -> str:
    ns = _namespace()
    if ns is None:  # pragma: no cover — orchestrator always sets these
        return json.dumps({"error": "memory tools require request context"})
    metadata = args.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    result = await memory_mod.save_memory(
        ns[0],
        ns[1],
        content=str(args.get("content", "")),
        kind=str(args.get("kind", "fact")),
        metadata=metadata,
    )
    return json.dumps(result, default=str)


async def _memory_search(args: dict[str, Any]) -> str:
    ns = _namespace()
    if ns is None:  # pragma: no cover — orchestrator always sets these
        return json.dumps({"error": "memory tools require request context"})
    kind = args.get("kind")
    result = await memory_mod.search_memories(
        ns[0],
        ns[1],
        query=str(args.get("query", "")),
        top_k=int(args.get("top_k", 5)),
        kind=str(kind) if kind else None,
    )
    return json.dumps(result, default=str)


memory_save = Tool(
    name="memory_save",
    description=(
        "Save a durable memory for this agent (facts about the user, stated "
        "preferences, or conversation summaries). Use when the user shares "
        "something worth remembering across sessions."
    ),
    handler=_memory_save,
    input_schema={
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The memory text to store (concise, self-contained).",
            },
            "kind": {
                "type": "string",
                "enum": list(memory_mod.MEMORY_KINDS),
                "description": "Memory category (default: fact).",
            },
            "metadata": {
                "type": "object",
                "description": "Optional small JSON metadata (e.g. source, topic).",
            },
        },
        "required": ["content"],
    },
)

memory_search = Tool(
    name="memory_search",
    description=(
        "Search this agent's saved memories by semantic similarity (falls "
        "back to keyword search). Use to recall facts, preferences, or past "
        "summaries relevant to the current conversation."
    ),
    handler=_memory_search,
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for."},
            "top_k": {
                "type": "integer",
                "description": "Max results (1-20, default 5).",
            },
            "kind": {
                "type": "string",
                "enum": list(memory_mod.MEMORY_KINDS),
                "description": "Optionally restrict to one memory kind.",
            },
        },
        "required": ["query"],
    },
)

MEMORY_TOOLS = [memory_save, memory_search]
MEMORY_TOOL_NAMES = frozenset(t.name for t in MEMORY_TOOLS)
