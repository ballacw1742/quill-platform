"""Input schema for the safety_aggregator (Safety Log Aggregator) agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SafetyPeriod(BaseModel):
    model_config = ConfigDict(extra="allow")

    start: str = Field(..., description="Period start date (ISO).")
    end: str = Field(..., description="Period end date (ISO).")


class IncidentRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    date: str = Field(..., description="Date of the incident (ISO).")
    type: Literal[
        "near_miss",
        "first_aid",
        "recordable",
        "lost_time",
        "property_damage",
        "fatality",
        "other",
    ] = Field(..., description="OSHA incident type.")
    description: str = Field(..., description="Description of what happened.")
    location: str = Field(..., description="Location on site where the incident occurred.")
    persons_involved: int = Field(..., description="Number of persons involved.")
    root_cause: str | None = Field(
        default=None, description="Identified root cause, if investigation is complete."
    )
    corrective_action: str | None = Field(
        default=None, description="Corrective action taken or planned."
    )


class ToolboxTalk(BaseModel):
    model_config = ConfigDict(extra="allow")

    date: str = Field(..., description="Date of the toolbox talk (ISO).")
    topic: str = Field(..., description="Topic covered in the toolbox talk.")
    attendees: int = Field(..., description="Number of attendees.")


class InspectionRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    date: str = Field(..., description="Inspection date (ISO).")
    inspector: str = Field(..., description="Inspector name or organization.")
    deficiencies_count: int = Field(..., description="Total deficiencies identified.")
    deficiencies_resolved_count: int = Field(
        ..., description="Number of deficiencies resolved at time of reporting."
    )


class SafetyAggregatorInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    project_label: str = Field(..., description="Free-text project identifier.")
    period: SafetyPeriod = Field(..., description="Reporting period (start and end dates).")
    incident_log: list[IncidentRecord] = Field(
        default_factory=list, description="All safety incidents during the period."
    )
    toolbox_talks: list[ToolboxTalk] = Field(
        default_factory=list, description="Toolbox talks conducted during the period."
    )
    inspections: list[InspectionRecord] = Field(
        default_factory=list, description="Safety inspections conducted during the period."
    )
