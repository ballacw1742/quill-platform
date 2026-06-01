"""safety_aggregator sub-agent — Safety log aggregator.

Ported from agentic-pmo-prompts/agents/safety-aggregator/.
"""
from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent

from .input_schema import SafetyAggregatorInput
from .output_schema import SafetyAggregatorOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="safety_aggregator",
    model=MODEL,
    description=(
        "Aggregates safety incident logs, toolbox talk records, and inspection results "
        "across a reporting period. Computes OSHA TRIR, identifies root cause trends, "
        "surfaces outstanding corrective actions, and produces a safety performance summary."
    ),
    instruction=_INSTRUCTION,
    input_schema=SafetyAggregatorInput,
    output_schema=SafetyAggregatorOutput,
)
