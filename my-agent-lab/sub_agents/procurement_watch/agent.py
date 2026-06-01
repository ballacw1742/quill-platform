"""procurement_watch sub-agent.

Ported from agentic-pmo-prompts/agents/procurement-watch/.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import ProcurementWatchInput
from .output_schema import ProcurementWatchOutputOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="procurement_watch",
    model=MODEL,
    description="Monitors long-lead procurement POs and flags critical-path threats.",
    instruction=_INSTRUCTION,
    input_schema=ProcurementWatchInput,
    output_schema=ProcurementWatchOutputOutput,
)
