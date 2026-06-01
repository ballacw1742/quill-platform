"""co_estimator sub-agent — Change Order estimator.

Ported from agentic-pmo-prompts/agents/co-estimator/.
"""
from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent

from .input_schema import CoEstimatorInput
from .output_schema import CoEstimatorOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="co_estimator",
    model=MODEL,
    description=(
        "Takes an approved CCB packet and produces a formal Change Order with "
        "line-item CSI cost breakdown, contractor markup, bonding, schedule impact, "
        "narrative justification, assumptions, and exclusions."
    ),
    instruction=_INSTRUCTION,
    input_schema=CoEstimatorInput,
    output_schema=CoEstimatorOutput,
)
