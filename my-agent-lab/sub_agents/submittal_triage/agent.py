"""submittal_triage sub-agent.

Ported from agentic-pmo-prompts/agents/submittal-triage/.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import SubmittalTriageInput
from .output_schema import SubmittalReviewOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="submittal_triage",
    model=MODEL,
    description="First-pass submittal disposition for design team review.",
    instruction=_INSTRUCTION,
    input_schema=SubmittalTriageInput,
    output_schema=SubmittalReviewOutput,
)
