"""submittal_spec_validator sub-agent.

Ported from agentic-pmo-prompts/agents/submittal-spec-validator/.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import SubmittalSpecValidatorInput
from .output_schema import SubmittalSpecValidationOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="submittal_spec_validator",
    model=MODEL,
    description="Line-by-line conformance report for submittal vs. spec section.",
    instruction=_INSTRUCTION,
    input_schema=SubmittalSpecValidatorInput,
    output_schema=SubmittalSpecValidationOutput,
)
