"""owner_reporting sub-agent — Owner-facing project status report.

Ported from agentic-pmo-prompts/agents/owner-reporting/.
"""
from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent

from .input_schema import OwnerReportingInput
from .output_schema import OwnerReportingOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="owner_reporting",
    model=MODEL,
    description=(
        "Produces executive-quality weekly/biweekly/monthly status reports for the project owner. "
        "Covers cost, schedule, milestones, change orders, safety, risks, and owner action items."
    ),
    instruction=_INSTRUCTION,
    input_schema=OwnerReportingInput,
    output_schema=OwnerReportingOutput,
)
