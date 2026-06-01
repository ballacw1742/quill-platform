"""Axe — root orchestration agent for Quill.

The chief-of-staff agent. Routes work to Quill PMO sub-agents.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import AxeInput
from sub_agents import ALL_SUB_AGENTS  # the list of sub-agent instances

MODEL = "gemini-3.1-pro-preview"

_INSTRUCTION = (Path(__file__).parent / "instruction.md").read_text(encoding="utf-8")

root_agent = LlmAgent(
    name="Axe",
    model=MODEL,
    description="Personal chief-of-staff agent; routes Quill PMO work to specialized sub-agents.",
    instruction=_INSTRUCTION,
    input_schema=AxeInput,
    sub_agents=ALL_SUB_AGENTS,
)
