from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class ClauseEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    pass

class ContractExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: Literal["contract_extraction"] = Field(..., description="Always 'contract_extraction'.")
    contract_type: Literal["owner_gc", "subcontract", "change_order", "purchase_order", "letter_of_intent", "nda", "msa", "equipment_lease", "insurance_certificate", "lien_waiver", "other", "unknown"] = Field(..., description="Detected contract type.")
    confidence: float = Field(..., description="Confidence score for the contract_type classification (0.0–1.0).")
    parties: list[dict[str, Any]] = Field(...)
    effective_date: str | None = Field(..., description="Contract execution or effective date (ISO 8601: YYYY-MM-DD), or null.")
    expiration_date: str | None = Field(..., description="Contract expiration, termination, or project completion date (ISO 8601), or null.")
    total_value_usd: float | None = Field(..., description="Total contract sum in USD, or null if not determinable.")
    payment_terms: str | None = Field(..., description="Brief description of payment terms, or null.")
    payment_schedule: list[dict[str, Any]] = Field(...)
    key_milestones: list[dict[str, Any]] = Field(...)
    obligations: dict[str, list[str]] = Field(..., description="Map of party name to list of primary obligation bullet points.")
    notable_clauses: dict[str, Any] = Field(..., description="Notable clauses by topic. Each is either null (not found) or {verbatim, paraphrase}.")
    notes: str = Field(..., description="Free-form notes about extraction uncertainty, partial documents, etc.")
    disclaimer: Literal["AI-generated analysis. This is not legal advice. Review with qualified counsel before relying on it for any binding decision."] = Field(..., description="Mandatory AI-output disclaimer. Must equal the canonical text exactly.")
    citations: list[dict[str, Any]] = Field(...)
