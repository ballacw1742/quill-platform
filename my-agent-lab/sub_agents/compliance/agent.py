"""compliance sub-agent — Sprint 5.2.

Answers compliance checklist / deadline / obligation questions by reading live
data from the Quill backend via FunctionTools.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import ComplianceInput
from .tools import COMPLIANCE_TOOLS

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="compliance",
    model=MODEL,
    description="Answers questions about compliance checklists, regulatory deadlines, and contract obligations.",
    instruction=_INSTRUCTION,
    input_schema=ComplianceInput,
    tools=COMPLIANCE_TOOLS,
)
