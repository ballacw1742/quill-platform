"""critical_path_watch sub-agent — Schedule risk watcher.

Ported from agentic-pmo-prompts/agents/critical-path-watch/.
"""
from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent

from .input_schema import CriticalPathWatchInput
from .output_schema import CriticalPathWatchOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="critical_path_watch",
    model=MODEL,
    description=(
        "Analyzes a schedule snapshot against recent actuals and flags activities "
        "on or trending toward the critical path. Provides recovery options and "
        "an executive summary for the project team."
    ),
    instruction=_INSTRUCTION,
    input_schema=CriticalPathWatchInput,
    output_schema=CriticalPathWatchOutput,
)
