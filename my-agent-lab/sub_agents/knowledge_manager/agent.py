"""knowledge_manager sub-agent.

Ported from agentic-pmo-prompts/agents/knowledge-manager/.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import KnowledgeManagerInput
from .output_schema import KnowledgeEntryOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="knowledge_manager",
    model=MODEL,
    description="Captures decisions, lessons learned, and patterns for institutional memory.",
    instruction=_INSTRUCTION,
    input_schema=KnowledgeManagerInput,
    output_schema=KnowledgeEntryOutput,
)
