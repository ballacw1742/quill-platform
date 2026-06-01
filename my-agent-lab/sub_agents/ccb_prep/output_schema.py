"""Output schema for the ccb_prep (Change Control Board Preparation) agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ImpactAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cost_delta_usd: float = Field(..., description="Net cost change in USD (positive = added cost).")
    schedule_delta_days: float = Field(
        ..., description="Net schedule change in calendar days (positive = delay)."
    )
    scope_delta_summary: str = Field(
        ..., description="Plain-English summary of how the scope would change."
    )
    quality_impact: str = Field(
        ..., description="Assessment of how this change affects quality of the finished work."
    )
    safety_impact: str = Field(
        ..., description="Assessment of how this change affects site or occupant safety."
    )


class AlternativeOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option: str = Field(..., description="Description of the alternative approach considered.")
    why_not: str = Field(..., description="Why this alternative was not recommended.")
    comparative_cost_delta_usd: float | None = Field(
        default=None,
        description="Estimated cost delta vs. proposed change in USD, if calculable.",
    )


class VotingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member_name: str = Field(..., description="Name and role of the CCB voting member.")
    vote: str | None = Field(
        default=None,
        description="Vote cast: 'approve', 'approve_with_conditions', 'reject', 'abstain'. Null if not yet voted.",
    )
    comment: str | None = Field(default=None, description="Optional comment from the voting member.")


class SupportingEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., description="Document type or source (e.g. 'RFI', 'spec section').")
    ref: str = Field(..., description="Document reference ID or file path.")
    excerpt: str = Field(..., description="Verbatim excerpt from the source document.")


class CcbPacketMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_id: str = Field(
        ...,
        description="Generated unique change ID (e.g. 'CCB-2024-001'). The agent generates this.",
    )
    project_label: str = Field(..., description="Project identifier, echoed from input.")
    change_title: str = Field(..., description="Concise title for the change (10 words or fewer).")
    change_classification: Literal[
        "scope",
        "cost",
        "schedule",
        "quality",
        "compliance",
        "owner_request",
        "design_error",
        "field_condition",
    ] = Field(..., description="Primary classification of the change.")
    summary: str = Field(..., description="Executive summary of the change in 2–3 sentences.")
    justification: str = Field(
        ...,
        description="Explanation of why this change is needed, referencing the originating inputs.",
    )
    impact_analysis: ImpactAnalysis = Field(
        ..., description="Structured analysis of cost, schedule, scope, quality, and safety impacts."
    )
    alternatives_considered: list[AlternativeOption] = Field(
        default_factory=list,
        description="Alternatives that were considered and why they were not recommended.",
    )
    recommendation: Literal[
        "approve", "approve_with_conditions", "reject", "defer_for_more_info"
    ] = Field(..., description="Agent's recommendation for the CCB vote.")
    recommendation_rationale: str = Field(
        ..., description="Explanation of why the agent is making this recommendation."
    )
    voting_record: list[VotingRecord] = Field(
        default_factory=list,
        description="Placeholder list for CCB member votes. Empty initially; populated by humans.",
    )
    supporting_evidence: list[SupportingEvidence] = Field(
        default_factory=list,
        description="Verbatim citations from the input documents supporting the analysis.",
    )


class CcbPrepOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifact_type: Literal["ccb_packet"] = Field(
        default="ccb_packet",
        description="Always 'ccb_packet' for routing.",
    )
    metadata: CcbPacketMetadata = Field(..., description="Full CCB preparation packet.")
    disclaimer: str = Field(
        default=(
            "AI-generated analysis. This is not legal advice. "
            "Review with qualified counsel before relying on it for any binding decision."
        ),
        description="Canonical AI disclaimer.",
    )
