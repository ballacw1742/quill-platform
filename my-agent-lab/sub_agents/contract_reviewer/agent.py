"""contract_reviewer sub-agent.

Ported from agentic-pmo-prompts/agents/contract-reviewer/.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import ContractReviewerInput
from .output_schema import ContractReviewOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="contract_reviewer",
    model=MODEL,
    description="Reviews extracted contracts for risk flags, missing protections, and market terms.",
    instruction=_INSTRUCTION,
    input_schema=ContractReviewerInput,
    output_schema=ContractReviewOutput,
)
