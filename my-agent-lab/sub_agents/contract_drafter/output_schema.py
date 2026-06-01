from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class ContractDraftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: Literal["contract_draft"] = Field(..., description="Always 'contract_draft'.")
    contract_type: str = Field(..., description="Contract type enum: owner_gc | subcontract | change_order | purchase_order | letter_of_intent | nda | msa | equipment_lease | insurance_certificate | ")
    mode: Literal["template", "negotiated"] = Field(..., description="Drafting mode — echoed from input.")
    template_id: str | None | None = Field(default=None, description="The template_id used, if mode=template. Null for negotiated mode.")
    parties: list[dict[str, Any]] = Field(..., description="Parties to the contract — echoed from input.")
    effective_date: str | None = Field(..., description="ISO-8601 effective date — echoed from input.")
    expiration_date: str | None | None = Field(default=None, description="ISO-8601 expiration date — echoed from input or null.")
    total_value_usd: float | None | None = Field(default=None, description="Contract value in USD — echoed from input or null.")
    title: str = Field(..., description="Display title for the drafted contract (e.g., 'Subcontract Agreement — ABC Framing LLC — Project Alpha').")
    summary: str = Field(..., description="100–200 word plain-English summary of what this contract does, who the parties are, what's covered, and the key financial/time terms.")
    body_markdown: str = Field(..., description="The full drafted contract as Markdown. This is the actual contract document. Must include all articles/sections, definitions, and a signature block. M")
    sections: list[dict[str, Any]] = Field(..., description="Section table of contents — one entry per major article or section in body_markdown.")
    variables_used: dict[str, Any] = Field(..., description="For template mode: map of variable name → value used. For negotiated mode: map of key decision points → value chosen.")
    key_terms_addressed: dict[str, str] = Field(..., description="For each item in key_terms_requested, how it is reflected in the draft. Key is the topic; value is a plain-English explanation.")
    assumptions_made: list[dict[str, Any]] = Field(..., description="Every place the agent filled in a missing variable or made a judgment call. Required for transparency.")
    attorney_review_focus: list[dict[str, Any]] = Field(..., description="At least 3 items — specific provisions counsel should scrutinize, with a concrete question to ask.")
    disclaimer: str = Field(..., description="Must be exactly: 'AI-generated analysis. This is not legal advice. Review with qualified counsel before relying on it for any binding decision.'")
    citations: list[dict[str, Any]] = Field(..., description="Legal citations, if any. Typically empty for drafted contracts — do not cite cases or statutes without verified sources.")
