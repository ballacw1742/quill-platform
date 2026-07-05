"""facility_ops sub-agent — Sprint 5.2.

Answers campus status / incident / PUE / uptime / power questions by reading
live data from the Quill backend via FunctionTools.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import FacilityOpsInput
from .tools import FACILITY_OPS_TOOLS

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="facility_ops",
    model=MODEL,
    description="Answers questions about campus status, incidents, PUE, uptime, and power metrics.",
    instruction=_INSTRUCTION,
    input_schema=FacilityOpsInput,
    tools=FACILITY_OPS_TOOLS,
)
