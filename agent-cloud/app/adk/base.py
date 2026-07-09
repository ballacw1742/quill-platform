"""TaskAgentRunner interface + result/context dataclasses (ADK_AGENTS_DESIGN.md §2).

A task-agent is invoked with a task string + a TaskContext and returns a
TaskResult. Unlike the Claude chat loop (app/orchestrator.py), a task-agent
is a one-shot "do the task, produce a deliverable or a proposal" call, not a
conversational turn. Both the real ADK runner and the test mock conform to
this interface so the dispatcher/overlay code is runtime-agnostic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class TaskContext:
    """Everything a task-agent needs to run under the right tenant/budget.

    A SHARED agent used by user B runs under B's tenant/budget: the caller
    constructs the context with B's tenant_id and user_id even though the
    agent definition was authored by another tenant (ADK_AGENTS_DESIGN.md §3).
    `allow_writes` is the governance gate: an unapproved agent runs with
    allow_writes=False (read + deliverable-generation only).
    """

    tenant_id: str
    agent_id: str
    user_id: str | None = None
    session_id: uuid.UUID | None = None
    # Governance: writes (approval-gated Quill mutations) only when True.
    # An unapproved / read-only invocation sets this False so the runner
    # never even offers the write tools to the model.
    allow_writes: bool = False
    # The agent definition's ADK spec (instruction/tools/model/output_schema).
    adk_config: dict[str, Any] = field(default_factory=dict)
    # The agent definition's tool allow-list (names in ADK_TOOL_REGISTRY).
    tools: list[str] = field(default_factory=list)
    model: str = ""
    system_prompt: str = ""


@dataclass
class TaskResult:
    """Structured task-agent result with token/cost accounting.

    `deliverables` are the Drive documents/sheets a task-agent produced.
    `proposals` are approval-gated writes it filed (each is a Quill approval
    item id + the agent-cloud proposal id). `tool_calls` is the ordered
    trace. token/cost feed budgets/meters exactly like a chat turn.
    """

    ok: bool
    agent_id: str
    tenant_id: str
    output: dict[str, Any] = field(default_factory=dict)
    deliverables: list[dict[str, Any]] = field(default_factory=list)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    budget_exceeded: bool = False
    error: str | None = None
    created_at: datetime = field(default_factory=_utcnow)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "agent_id": self.agent_id,
            "tenant_id": self.tenant_id,
            "output": self.output,
            "deliverables": self.deliverables,
            "proposals": self.proposals,
            "tool_calls": self.tool_calls,
            "model": self.model,
            "usage": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cost_usd": round(self.cost_usd, 6),
            },
            "budget_exceeded": self.budget_exceeded,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
        }


class TaskAgentRunner(Protocol):
    """The runner contract. Implementations: AdkAgentRunner (real, google-adk)
    and test mocks. `run` must never raise on a task-level failure \u2014 it
    returns TaskResult(ok=False, error=...). It may raise only on programmer
    errors (bad context)."""

    async def run(self, task: str, context: TaskContext) -> TaskResult: ...
