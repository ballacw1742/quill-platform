"""sales sub-agent — Sprint 5.2.

Answers deal / pipeline / account / activity questions by reading live data
from the Quill backend via FunctionTools.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import SalesInput
from .tools import SALES_TOOLS

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="sales",
    model=MODEL,
    description="Answers questions about deals, accounts, pipeline value, win rates, and activity history.",
    instruction=_INSTRUCTION,
    input_schema=SalesInput,
    tools=SALES_TOOLS,
)
