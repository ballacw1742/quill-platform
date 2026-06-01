"""design_classifier sub-agent.

Ported from agentic-pmo-prompts/agents/design-classifier/.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import DesignClassifierInput
from .output_schema import AaceClassificationOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="design_classifier",
    model=MODEL,
    description="Classifies design packages per AACE 18R-97/56R-08 (Class 5/4/3/2).",
    instruction=_INSTRUCTION,
    input_schema=DesignClassifierInput,
    output_schema=AaceClassificationOutput,
)
