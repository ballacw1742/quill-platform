"""estimator_scheduler sub-agent.

Ported from agentic-pmo-prompts/agents/estimator-scheduler/.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import EstimatorSchedulerInput
from .output_schema import CostSchedulePackageOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="estimator_scheduler",
    model=MODEL,
    description="Produces cost-code estimates and schedules from approved AACE classification.",
    instruction=_INSTRUCTION,
    input_schema=EstimatorSchedulerInput,
    output_schema=CostSchedulePackageOutput,
)
