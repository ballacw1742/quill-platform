"""Input schema for the ccb_prep (Change Control Board Preparation) agent."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SupportingDocumentRef(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str = Field(..., description="Document type, e.g. 'RFI', 'drawing', 'spec section', 'email'.")
    ref: str = Field(..., description="Document reference ID or file path.")
    summary: str = Field(..., description="One- or two-sentence summary of what this document says.")


class CcbPrepInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    project_label: str = Field(..., description="Free-text project identifier, e.g. 'QPB1 — Tower A'.")
    change_summary: str = Field(..., description="One-line description of the candidate change.")
    originating_rfi_id: str | None = Field(
        default=None,
        description="RFI ID that triggered this change request, if any.",
    )
    originating_directive: str | None = Field(
        default=None,
        description="Verbatim text of the owner or architect directive that triggered this change, if any.",
    )
    current_scope_excerpt: str = Field(
        ...,
        description="Relevant excerpts from the contract or specifications describing the current agreed scope.",
    )
    proposed_scope_change: str = Field(
        ...,
        description="Plain-English description of what would change if this request is approved.",
    )
    cost_estimate_usd: float | None = Field(
        default=None,
        description="Preliminary cost estimate in USD, if available. May be None if not yet estimated.",
    )
    schedule_impact_days: float | None = Field(
        default=None,
        description="Estimated schedule impact in calendar days (positive = delay, negative = acceleration).",
    )
    supporting_documents: list[SupportingDocumentRef] = Field(
        default_factory=list,
        description="List of supporting documents (drawings, RFIs, emails, specs) relevant to this change.",
    )
