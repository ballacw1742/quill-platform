"""project_manager sub-agent.

Ported from agentic-pmo-prompts/agents/project-manager/.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import ProjectManagerInput
from .output_schema import PmAnalysisOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="project_manager",
    model=MODEL,
    description="On-demand analytical work: scope/cost/schedule/risk questions synthesized into exec-ready analyses.",
    instruction=_INSTRUCTION,
    input_schema=ProjectManagerInput,
    output_schema=PmAnalysisOutput,
)
