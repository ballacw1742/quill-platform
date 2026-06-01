"""daily_brief sub-agent.

Ported from agentic-pmo-prompts/agents/daily-brief/.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import DailyBriefInput
from .output_schema import DailyBriefOutputOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="daily_brief",
    model=MODEL,
    description="Morning digest agent. Produces a structured daily brief for Charles at 7:00 AM ET.",
    instruction=_INSTRUCTION,
    input_schema=DailyBriefInput,
    output_schema=DailyBriefOutputOutput,
)
