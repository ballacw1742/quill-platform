"""status_update_author sub-agent.

Ported from agentic-pmo-prompts/agents/status-update-author/.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import StatusUpdateAuthorInput
from .output_schema import StatusUpdateDraftOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="status_update_author",
    model=MODEL,
    description="Drafts weekly project status updates from operational data. Never sends.",
    instruction=_INSTRUCTION,
    input_schema=StatusUpdateAuthorInput,
    output_schema=StatusUpdateDraftOutput,
)
