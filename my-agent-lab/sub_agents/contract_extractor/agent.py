"""contract_extractor sub-agent.

Ported from agentic-pmo-prompts/agents/contract-extractor/.
"""
from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .input_schema import ContractExtractorInput
from .output_schema import ContractExtractionOutput

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="contract_extractor",
    model=MODEL,
    description="Extracts structured fields from construction contract documents. No legal opinions.",
    instruction=_INSTRUCTION,
    input_schema=ContractExtractorInput,
    output_schema=ContractExtractionOutput,
)
