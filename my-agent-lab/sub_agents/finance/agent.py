"""finance sub-agent — Sprint 5.2.

Answers ARR / invoice / cash / capex / budget questions by reading live data
from the Quill backend via FunctionTools.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import FinanceInput
from .tools import FINANCE_TOOLS

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="finance",
    model=MODEL,
    description="Answers questions about ARR, invoices, cash position, capex, and budget vs actuals.",
    instruction=_INSTRUCTION,
    input_schema=FinanceInput,
    tools=FINANCE_TOOLS,
)
