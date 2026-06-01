"""Input schema for the progress_capture (Site Photo/Video Progress) agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MediaRef(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: Literal["photo", "video"] = Field(..., description="Media type.")
    file_ref: str = Field(
        ..., description="File reference (local path, GCS URI, or HTTPS URL)."
    )
    view_direction: str | None = Field(
        default=None,
        description="Viewing direction or angle (e.g. 'north', 'looking east', 'overhead').",
    )


class PriorCaptureEstimate(BaseModel):
    model_config = ConfigDict(extra="allow")

    scope: str = Field(..., description="Scope item name.")
    percent_complete: float = Field(..., description="Prior capture's percent complete estimate (0–100).")
    date: str = Field(..., description="Date of the prior capture (ISO).")


class ProgressCaptureInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    project_label: str = Field(..., description="Free-text project identifier.")
    capture_date: str = Field(..., description="Date of the site capture (ISO date, YYYY-MM-DD).")
    location_label: str = Field(
        ..., description="Location description (e.g. 'Level 3 — east bay', 'Foundation — Grid A-C/1-4')."
    )
    media_refs: list[MediaRef] = Field(
        ..., description="List of media files to analyze."
    )
    expected_scopes_in_view: list[str] = Field(
        default_factory=list,
        description=(
            "List of scope items expected to be visible at this location "
            "(e.g. 'structural steel', 'metal deck', 'MEP rough-in'). "
            "Helps the agent focus its analysis."
        ),
    )
    prior_capture_estimates: list[PriorCaptureEstimate] | None = Field(
        default=None,
        description="Prior capture estimates for delta tracking. If provided, the agent computes deltas.",
    )
