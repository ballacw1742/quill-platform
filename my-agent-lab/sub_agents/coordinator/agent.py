"""coordinator sub-agent.

Ported from agentic-pmo-prompts/agents/coordinator/.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import CoordinatorInput
from .output_schema import CoordinatorOutputOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="coordinator",
    model=MODEL,
    description="Routes inbound requests, decomposes plans, dispatches sub-agent tasks.",
    instruction=_INSTRUCTION,
    input_schema=CoordinatorInput,
    output_schema=CoordinatorOutputOutput,
)
