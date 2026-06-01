"""Output schema for the progress_capture (Site Photo/Video Progress) agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IdentifiedScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str = Field(..., description="Scope item name (should match an item from expected_scopes_in_view).")
    visible_pct_complete: float = Field(
        ..., description="Agent's estimate of percent complete (0–100), based on what's visible."
    )
    evidence_from_media: str = Field(
        ...,
        description=(
            "Plain-English description of what the agent saw in the media that supports "
            "this percent-complete estimate."
        ),
    )
    confidence: float = Field(
        ...,
        description=(
            "Confidence in the estimate (0.0–1.0). "
            "Use lower values when the media is partial, obscured, or ambiguous."
        ),
    )


class QualityObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str = Field(..., description="Scope item this observation relates to.")
    observation: str = Field(..., description="Description of the quality observation.")
    severity: Literal["info", "concern", "defect"] = Field(
        ...,
        description=(
            "info: noteworthy but not a problem. "
            "concern: may become a defect if not addressed. "
            "defect: non-conformance that needs correction."
        ),
    )


class SafetyObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation: str = Field(..., description="Description of the safety observation.")
    severity: Literal["info", "concern", "violation"] = Field(
        ...,
        description=(
            "info: general safety note. "
            "concern: potential hazard. "
            "violation: clear safety rule violation requiring immediate action."
        ),
    )


class ProgressDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str = Field(..., description="Scope item name.")
    prior_pct: float = Field(..., description="Prior capture percent complete.")
    current_pct: float = Field(..., description="Current capture percent complete.")
    delta_pct: float = Field(
        ..., description="current_pct - prior_pct. Positive = progress made."
    )


class SiteProgressCaptureMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_label: str
    capture_date: str
    location_label: str
    identified_scopes: list[IdentifiedScope] = Field(
        default_factory=list,
        description="Scope items identified and their percent-complete estimates.",
    )
    quality_observations: list[QualityObservation] = Field(
        default_factory=list,
        description="Quality observations from the media.",
    )
    safety_observations: list[SafetyObservation] = Field(
        default_factory=list,
        description="Safety observations from the media.",
    )
    progress_deltas_vs_prior: list[ProgressDelta] | None = Field(
        default=None,
        description="Delta vs. prior capture, populated only if prior_capture_estimates was provided.",
    )
    summary: str = Field(
        ...,
        description=(
            "Plain-English summary of what the media shows: overall progress, "
            "key observations, and any concerns."
        ),
    )


class ProgressCaptureOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifact_type: Literal["site_progress_capture"] = Field(
        default="site_progress_capture",
        description="Always 'site_progress_capture' for routing.",
    )
    metadata: SiteProgressCaptureMetadata = Field(
        ..., description="Full site progress capture analysis."
    )
    disclaimer: str = Field(
        default=(
            "AI-generated analysis. This is not legal advice. "
            "Review with qualified counsel before relying on it for any binding decision."
        ),
        description="Canonical AI disclaimer.",
    )
