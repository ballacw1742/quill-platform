from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class Markettermsentry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["in-market", "off-market-favorable", "off-market-unfavorable", "not-present", "unclear"] = Field(..., description="in-market = standard/reasonable; off-market-favorable = better than typical for owner; off-market-unfavorable = worse than typical for owner; not-pres")
    notes: str = Field(..., description="1-3 sentence explanation of the verdict. Acknowledge jurisdiction-specific variation where relevant.")

class ContractReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_flags: list[dict[str, Any]] = Field(..., description="Identified risks and unfavorable terms in the contract.")
    missing_protections: list[dict[str, Any]] = Field(..., description="Common protective provisions that are notably absent from this contract.")
    market_terms_assessment: dict[str, Any] = Field(..., description="Per-category assessment of whether terms are in-market, off-market-favorable, or off-market-unfavorable. Uses Ohio commercial construction context.")
    plain_english_summary: str = Field(..., description="200–300 word plain-English summary of the entire agreement, written in chief-of-staff voice. No legalese.")
    recommended_actions: list[str] = Field(..., description="Ordered list of next steps the user should take before signing or relying on this contract.")
    disclaimer: Literal["AI-generated analysis. This is not legal advice. Review with qualified counsel before relying on it for any binding decision."] = Field(..., description="Canonical disclaimer — must match exactly.")
    citations: list[dict[str, Any]] = Field(..., description="Supporting citations from the contract text.")
