"""contract_interpreter sub-agent.

Ported from agentic-pmo-prompts/agents/contract-interpreter/.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import ContractInterpreterInput
from .output_schema import ContractInterpretationOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="contract_interpreter",
    model=MODEL,
    description="Answers plain-English questions about contract clauses with citations and confidence.",
    instruction=_INSTRUCTION,
    input_schema=ContractInterpreterInput,
    output_schema=ContractInterpretationOutput,
)
