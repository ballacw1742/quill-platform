"""Per-tenant seed agent definitions: "personal" + "quill" (design doc §3.3).

Provisioning runs on first contact (endpoint is IAM-gated; product signup
provisioning replaces this in Phase B). Seeds are INSERT ... ON CONFLICT DO
NOTHING — existing definitions are never overwritten.

Model tiering: default tier = MODEL_DEFAULT (claude-fable-5); cheap tier =
MODEL_CHEAP (claude-haiku-4-5). Tenants whose id starts with "smoke-" seed
on the cheap tier — test/probe convention so verification loops never burn
default-tier tokens.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.tools.builtin import BUILTIN_TOOLS
from app.tools.memory import MEMORY_TOOLS
from app.tools.quill import QUILL_TOOLS
from app.tools.quill_writes import QUILL_WRITE_TOOLS

SMOKE_TENANT_PREFIX = "smoke-"

PERSONAL_SYSTEM_PROMPT = (
    "You are the personal assistant agent for tenant {tenant_id} on Quill "
    "Agent Cloud. Be concise, helpful, and direct. Use your tools when they "
    "help. Save durable facts, preferences, and summaries with memory_save; "
    "recall them with memory_search. You do not have access to Quill "
    "business data tools; if asked for Quill financials or operations, "
    "suggest the tenant's 'quill' agent."
)

QUILL_SYSTEM_PROMPT = (
    "You are the Quill business agent for tenant {tenant_id} on Quill Agent "
    "Cloud. You answer questions about the Quill portfolio using your "
    "read-only tools: finance, sales pipeline, operations (campuses), "
    "customers, the morning intelligence brief, and the pending approvals "
    "queue. Cite concrete numbers from tool results. You cannot write or "
    "approve anything — all writes go through the human approval queue."
)


@dataclass(frozen=True)
class SeedAgent:
    agent_id: str
    system_prompt: str
    tools: tuple[str, ...]
    # off | tools_only | auto_recall (A2 memory subsystem)
    memory_policy: str = "off"


SEED_AGENTS = (
    SeedAgent(
        agent_id="personal",
        system_prompt=PERSONAL_SYSTEM_PROMPT,
        tools=tuple(t.name for t in BUILTIN_TOOLS)
        + tuple(t.name for t in MEMORY_TOOLS),
        memory_policy="auto_recall",  # design §3.3: personal agent, memory on
    ),
    SeedAgent(
        agent_id="quill",
        system_prompt=QUILL_SYSTEM_PROMPT,
        tools=tuple(t.name for t in BUILTIN_TOOLS)
        + tuple(t.name for t in QUILL_TOOLS)
        + tuple(t.name for t in QUILL_WRITE_TOOLS),
        memory_policy="off",
    ),
)


def seed_model_for_tenant(tenant_id: str) -> str:
    s = get_settings()
    if tenant_id.startswith(SMOKE_TENANT_PREFIX):
        return s.MODEL_CHEAP
    return s.MODEL_DEFAULT
