"""rfi_triage sub-agent.

Ported from agentic-pmo-prompts/agents/rfi-triage/.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import RfiTriageInput
from .output_schema import RfiClassificationOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="rfi_triage",
    model=MODEL,
    description="Classifies inbound RFIs and proposes routing to the right responder.",
    instruction=_INSTRUCTION,
    input_schema=RfiTriageInput,
    output_schema=RfiClassificationOutput,
)
