from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class ContractInterpretationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., description="Echo of the user's question.")
    answer: str = Field(..., description="Plain-English answer to the question. Default 100–300 words; may be longer for complex questions.")
    supporting_clauses: list[dict[str, Any]] = Field(..., description="Contract clauses that directly support the answer.")
    confidence: float = Field(..., description="Confidence score 0–1. 1.0 = answer is unambiguous from explicit contract text; 0.0 = highly uncertain (clause absent, ambiguous, or conflicting).")
    caveats: list[dict[str, Any]] = Field(..., description="Situations where the answer could be wrong or depend on additional context.")
    disclaimer: Literal["AI-generated analysis. This is not legal advice. Review with qualified counsel before relying on it for any binding decision."] = Field(..., description="Canonical disclaimer — must match exactly.")
