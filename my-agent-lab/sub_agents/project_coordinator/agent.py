"""project_coordinator sub-agent.

Ported from agentic-pmo-prompts/agents/project-coordinator/.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import ProjectCoordinatorInput
from .output_schema import CoordinatorArtifactOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="project_coordinator",
    model=MODEL,
    description="Produces SOPs, RACI matrices, meeting agendas, action items, and process docs.",
    instruction=_INSTRUCTION,
    input_schema=ProjectCoordinatorInput,
    output_schema=CoordinatorArtifactOutput,
)
