"""comms_drafter sub-agent.

Ported from agentic-pmo-prompts/agents/comms-drafter/.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import CommsDrafterInput
from .output_schema import CommsDraftOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="comms_drafter",
    model=MODEL,
    description="Drafts owner/partner/sub/vendor/internal communications for human review. Never sends.",
    instruction=_INSTRUCTION,
    input_schema=CommsDrafterInput,
)
