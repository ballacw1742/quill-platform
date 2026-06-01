"""ccb_prep sub-agent — Change Control Board preparation packet.

Ported from agentic-pmo-prompts/agents/ccb-prep/.
"""
from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent

from .input_schema import CcbPrepInput
from .output_schema import CcbPrepOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="ccb_prep",
    model=MODEL,
    description=(
        "Transforms a candidate change request (RFI follow-up, scope discovery, owner directive) "
        "into a decision-ready CCB briefing packet with impact analysis, alternatives, "
        "and a voting recommendation."
    ),
    instruction=_INSTRUCTION,
    input_schema=CcbPrepInput,
    output_schema=CcbPrepOutput,
)
