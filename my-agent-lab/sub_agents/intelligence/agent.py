"""intelligence sub-agent — Sprint 5.2.

Produces cross-module executive briefings by reading summary endpoints across
Operations, Sales, Finance, and Customer Success via FunctionTools.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import IntelligenceInput
from .tools import INTELLIGENCE_TOOLS

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="intelligence",
    model=MODEL,
    description="Provides cross-module executive summaries: business health, risk flags, and KPI rollups.",
    instruction=_INSTRUCTION,
    input_schema=IntelligenceInput,
    tools=INTELLIGENCE_TOOLS,
)
