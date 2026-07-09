"""Google ADK task-agent runtime (ADK_AGENTS_DESIGN.md §2).

Public surface:
  TaskAgentRunner  — the runner interface (run(task, context) -> TaskResult).
  TaskResult       — structured result with token/cost accounting.
  TaskContext      — invocation context (tenant/agent/user/session).
  AdkAgentRunner   — the real Google ADK runner (google-adk); MOCK-friendly.
  get_runner       — factory: picks the runner for an agent runtime.
  ADK_TOOL_REGISTRY / adk_tool_specs — curated ADK tool registry.
"""

from __future__ import annotations

from app.adk.base import TaskAgentRunner, TaskContext, TaskResult
from app.adk.registry import (
    ADK_TOOL_REGISTRY,
    DELIVERABLE_TOOL_NAMES,
    READ_TOOL_NAMES,
    WRITE_TOOL_NAMES,
    adk_tool_specs,
)
from app.adk.runner import AdkAgentRunner, AdkImportError, get_runner

__all__ = [
    "TaskAgentRunner",
    "TaskContext",
    "TaskResult",
    "AdkAgentRunner",
    "AdkImportError",
    "get_runner",
    "ADK_TOOL_REGISTRY",
    "DELIVERABLE_TOOL_NAMES",
    "READ_TOOL_NAMES",
    "WRITE_TOOL_NAMES",
    "adk_tool_specs",
]
