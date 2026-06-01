"""dfr_synthesizer sub-agent — Daily Field Report synthesizer.

Ported from agentic-pmo-prompts/agents/dfr-synthesizer/.
"""
from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent

from .input_schema import DfrSynthesizerInput
from .output_schema import DfrSynthesizerOutput
from tools.image_analysis import analyze_image_tool

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="dfr_synthesizer",
    model=MODEL,
    description=(
        "Synthesizes raw field inputs (superintendent notes, crew rosters, work logs, "
        "photo captions, equipment and delivery records) into a polished Daily Field Report."
    ),
    instruction=_INSTRUCTION,
    input_schema=DfrSynthesizerInput,
    output_schema=DfrSynthesizerOutput,
    tools=[analyze_image_tool],
)
