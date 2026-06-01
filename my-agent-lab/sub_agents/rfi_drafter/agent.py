"""rfi_drafter sub-agent.

Ported from agentic-pmo-prompts/agents/rfi-drafter/.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import RfiDrafterInput
from .output_schema import RfiResponseDraftOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="rfi_drafter",
    model=MODEL,
    description="Drafts RFI responses for engineer-of-record review. Never sends.",
    instruction=_INSTRUCTION,
    input_schema=RfiDrafterInput,
    output_schema=RfiResponseDraftOutput,
)
