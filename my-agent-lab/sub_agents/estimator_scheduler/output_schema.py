from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class PackageMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_label: str = Field(..., description="Echoed from the AACEClassification input.")
    aace_class: Literal["5", "4", "3", "2"] = Field(..., description="AACE class — INPUT, not the agent's choice. Comes from the approved AACEClassification artifact.")
    schedule_level: int = Field(..., description="Schedule level: 1 = exec summary, 5 = detailed CPM. Per AACE convention: Class 5 -> Level 1, Class 4 -> Level 2, Class 3 -> Level 3, Class 2 -> Level ")
    currency: Literal["USD"] = Field(...)
    base_year: str = Field(...)
    estimate: Estimate = Field(...)
    schedule: Schedule = Field(...)
    basis_of_estimate: str = Field(..., description="Plain-English basis-of-estimate narrative: scope assumptions, exclusions, source rates, quantity-takeoff method, escalation logic, contingency rationa")
    basis_of_schedule: str = Field(..., description="Plain-English basis-of-schedule narrative: WBS approach, calendars, productivity assumptions, weather allowances, long-lead drivers, critical-path exp")
    risk_register: list[RiskItem] = Field(...)
    missing_info_to_next_class: list[MissingItem] = Field(...)
    uploaded_files: list[UploadedFile] = Field(...)
    library_version: str = Field(..., description="Cost library version consulted for rates.")
    headline_metrics: dict[str, Any] | None = Field(default=None, description="Convenience top-line numbers, duplicated from estimate.* for fast list-view rendering.")

class Estimate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[EstimateRow] = Field(...)
    subtotal_direct_usd: float = Field(...)
    indirects: list[IndirectItem] = Field(...)
    contingency: Contingency = Field(...)
    escalation: Escalation | None = Field(default=None)
    total_usd: float = Field(...)
    total_per_sf_usd: float | None | None = Field(default=None)
    total_per_mw_usd: float | None | None = Field(default=None)

class EstimateRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csi_section: str = Field(...)
    description: str = Field(...)
    quantity: float = Field(...)
    unit: Literal["EA", "SF", "CY", "LB", "LF", "LS", "HR", "CF", "TON", "MWHr", "MW", "GAL", "KIP"] = Field(...)
    unit_rate_usd: float = Field(...)
    extended_usd: float = Field(..., description="quantity * unit_rate_usd; the agent must compute and emit it.")
    rate_source: str = Field(..., description="Free-form rate-source label set by the agent. Conventional values are listed in the estimator-scheduler prompt for routing consistency, but free-form ")
    confidence: float = Field(...)
    notes: str | None = Field(default=None)
    source_citation: str | None = Field(default=None, description="Drawing reference, IFC entity ID, DXF layer, or library row that supports the quantity. Per Hard Rule #2 every quantity row must cite a source; rows b")

class IndirectItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(...)
    pct_of_direct: float | None | None = Field(default=None)
    amount_usd: float = Field(...)
    notes: str | None = Field(default=None)

class Contingency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pct_of_direct_plus_indirect: float = Field(...)
    amount_usd: float = Field(...)
    rationale: str = Field(...)

class Escalation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    annual_pct: float = Field(...)
    midpoint_year: str = Field(...)
    amount_usd: float = Field(...)

class Schedule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: int = Field(...)
    activities: list[Activity] = Field(...)
    milestones: list[Milestone] | None = Field(default=None)
    total_duration_days: int = Field(...)
    critical_path_ids: list[str] | None = Field(default=None)
    calendar_assumptions: str | None = Field(default=None, description="Working calendar, weather days, holidays, shift patterns.")

class Activity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(...)
    name: str = Field(...)
    wbs: str | None = Field(default=None)
    duration_days: int = Field(...)
    predecessors: list[Predecessor] | None = Field(default=None)
    resources: list[Resource] | None = Field(default=None)
    milestone: bool | None = Field(default=None)
    critical_path: bool | None = Field(default=None)
    notes: str | None = Field(default=None)

class Predecessor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(...)
    type: Literal["FS", "SS", "FF", "SF"] = Field(...)
    lag_days: int | None = Field(default=None)

class Resource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(...)
    quantity: float = Field(...)
    unit: str | None = Field(default=None)

class Milestone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(...)
    name: str = Field(...)
    target_date: str | None | None = Field(default=None)
    achieved_at: str | None | None = Field(default=None)
    notes: str | None = Field(default=None)

class RiskItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(...)
    description: str = Field(...)
    category: str = Field(..., description="Free-form risk category label. Conventional values are documented in the estimator-scheduler prompt; free-form labels are accepted to match natural ag")
    likelihood: Literal["low", "medium", "high"] = Field(...)
    impact_usd_low: float | None | None = Field(default=None)
    impact_usd_high: float | None | None = Field(default=None)
    schedule_impact_days_low: int | None | None = Field(default=None)
    schedule_impact_days_high: int | None | None = Field(default=None)
    mitigation: str | None = Field(default=None)
    owner_role: str | None = Field(default=None)

class MissingItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deliverable: str = Field(...)
    rationale: str = Field(...)
    would_unlock_class: Literal["4", "3", "2"] = Field(...)
    estimated_cost_to_complete_usd: float | None | None = Field(default=None)

class UploadedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(...)
    kind: Literal["pdf", "ifc", "dwg", "dxf", "rvt", "other"] = Field(...)
    size_bytes: int = Field(...)
    extraction_status: Literal["ok", "partial", "failed"] = Field(...)
    extraction_summary: str | None = Field(default=None)
    minio_key: str | None = Field(default=None)

class CostSchedulePackageOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifact_type: Literal["cost_schedule_package"] = Field(...)
    metadata: PackageMetadata = Field(...)
