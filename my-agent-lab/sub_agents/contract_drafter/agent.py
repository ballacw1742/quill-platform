"""contract_drafter sub-agent.

Ported from agentic-pmo-prompts/agents/contract-drafter/.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import ContractDrafterInput
from .output_schema import ContractDraftOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="contract_drafter",
    model=MODEL,
    description="Drafts construction/business contracts from scratch or templates. Tier-0 mandatory review.",
    instruction=_INSTRUCTION,
    input_schema=ContractDrafterInput,
    output_schema=ContractDraftOutput,
)
