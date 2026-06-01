"""Input schema for the dfr_synthesizer (Daily Field Report Synthesizer) agent."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class WeatherData(BaseModel):
    model_config = ConfigDict(extra="allow")

    high_f: float = Field(..., description="High temperature in degrees Fahrenheit.")
    low_f: float = Field(..., description="Low temperature in degrees Fahrenheit.")
    conditions: str = Field(..., description="Weather conditions (e.g. 'Partly cloudy', 'Rain', 'Clear').")
    precipitation_in: float | None = Field(
        default=None, description="Precipitation in inches, if any."
    )


class CrewLogEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    trade: str = Field(..., description="Trade type (e.g. 'Concrete', 'Structural Steel', 'MEP').")
    contractor: str = Field(..., description="Subcontractor or GC company name.")
    headcount: int = Field(..., description="Number of workers on site today.")
    hours_worked: float = Field(..., description="Total worker-hours for the trade today.")
    foreman: str | None = Field(default=None, description="Foreman name, if recorded.")


class WorkPerformed(BaseModel):
    model_config = ConfigDict(extra="allow")

    location: str = Field(..., description="Site location (e.g. 'Level 3 — east bay', 'Foundations — Grid A').")
    scope: str = Field(..., description="Description of work performed.")
    percent_complete_today: float | None = Field(
        default=None,
        description="Percent of this scope item complete as of end of day (0–100).",
    )


class DeliveryRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    item: str = Field(..., description="Description of delivered material or equipment.")
    supplier: str = Field(..., description="Supplier or vendor name.")
    quantity: str = Field(..., description="Quantity delivered (with units, e.g. '24 CY', '3 bundles').")
    time_received: str = Field(..., description="Time received on site (e.g. '08:30', '14:15').")


class EquipmentRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    equipment: str = Field(..., description="Equipment description (e.g. 'Tower crane TC-01', '50T rough terrain crane').")
    operator: str | None = Field(default=None, description="Operator name, if recorded.")
    hours_used: float = Field(..., description="Hours the equipment was in use today.")


class IssueRaised(BaseModel):
    model_config = ConfigDict(extra="allow")

    category: str = Field(
        ...,
        description="Issue category (e.g. 'Safety', 'Quality', 'Schedule', 'Design', 'Materials').",
    )
    description: str = Field(..., description="Description of the issue.")
    severity: str = Field(
        ...,
        description="Severity level: 'info', 'low', 'medium', 'high', or 'critical'.",
    )


class PhotoRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    caption: str = Field(..., description="Photo caption describing what was photographed.")
    location: str = Field(..., description="Site location where the photo was taken.")
    taken_at: str = Field(..., description="Time the photo was taken (e.g. '10:45').")
    file_ref: str = Field(..., description="File reference (path, URL, or storage key).")


class DfrSynthesizerInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    project_label: str = Field(..., description="Free-text project identifier.")
    report_date: str = Field(..., description="Date of the field report (ISO date, YYYY-MM-DD).")
    weather: WeatherData = Field(..., description="Weather conditions for the day.")
    crew_log: list[CrewLogEntry] = Field(
        default_factory=list,
        description="Crew roster by trade.",
    )
    work_performed: list[WorkPerformed] = Field(
        default_factory=list,
        description="Work items performed today, by location.",
    )
    deliveries: list[DeliveryRecord] = Field(
        default_factory=list,
        description="Materials and equipment delivered to site today.",
    )
    equipment_on_site: list[EquipmentRecord] = Field(
        default_factory=list,
        description="Equipment on site today.",
    )
    issues_raised: list[IssueRaised] = Field(
        default_factory=list,
        description="Issues, concerns, or incidents raised today.",
    )
    photos: list[PhotoRecord] = Field(
        default_factory=list,
        description="Photos taken today with captions and locations.",
    )
    raw_notes: str = Field(
        default="",
        description="Free-text notes from the superintendent or field engineer.",
    )
