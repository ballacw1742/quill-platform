"""Output schema for the co_estimator (Change Order Estimator) agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CostRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csi_section: str = Field(
        ..., description="CSI MasterFormat section number (e.g. '03 30 00' for Cast-in-Place Concrete)."
    )
    description: str = Field(..., description="Plain-English description of the work item.")
    quantity: float = Field(..., description="Quantity of work.")
    unit: str = Field(..., description="Unit of measure (e.g. 'CY', 'LF', 'SF', 'EA', 'LS').")
    unit_rate_usd: float = Field(..., description="Unit cost in USD.")
    extended_usd: float = Field(..., description="quantity × unit_rate_usd.")
    source: str = Field(
        ...,
        description="Source of the unit rate (e.g. 'cost_library_reference', 'RS Means 2024', 'engineering judgment').",
    )


class Assumption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(..., description="Subject of the assumption (e.g. 'Site access', 'Concrete mix design').")
    assumption: str = Field(..., description="The specific assumption made.")


class ChangeOrderMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    co_number: str = Field(..., description="Change Order number (e.g. 'CO-001').")
    co_date: str = Field(..., description="ISO date the change order was generated.")
    references_ccb_id: str = Field(..., description="The CCB change_id this CO is based on.")
    project_label: str = Field(..., description="Project identifier, echoed from the CCB packet.")
    cost_rows: list[CostRow] = Field(
        default_factory=list,
        description="Line-item cost breakdown by CSI section.",
    )
    subtotal_direct_usd: float = Field(..., description="Sum of all extended_usd values.")
    contractor_markup_usd: float = Field(
        ..., description="Contractor O&P markup (subtotal_direct × markup_pct / 100)."
    )
    bonding_insurance_usd: float = Field(
        ..., description="Bonding and insurance (subtotal_direct × bonding_pct / 100)."
    )
    total_co_value_usd: float = Field(
        ...,
        description="Total change order value: subtotal_direct + contractor_markup + bonding_insurance.",
    )
    schedule_impact_days: float = Field(
        ..., description="Schedule impact in calendar days, echoed from the CCB packet."
    )
    narrative_justification: str = Field(
        ...,
        description=(
            "3–5 paragraph narrative explaining the cost build-up, "
            "cross-referencing the CCB packet."
        ),
    )
    assumptions: list[Assumption] = Field(
        default_factory=list,
        description="Explicit assumptions underlying the estimate.",
    )
    exclusions: list[str] = Field(
        default_factory=list,
        description="Items explicitly excluded from this change order.",
    )


class CoEstimatorOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifact_type: Literal["change_order"] = Field(
        default="change_order",
        description="Always 'change_order' for routing.",
    )
    metadata: ChangeOrderMetadata = Field(..., description="Full change order data.")
    disclaimer: str = Field(
        default=(
            "AI-generated analysis. This is not legal advice. "
            "Review with qualified counsel before relying on it for any binding decision."
        ),
        description="Canonical AI disclaimer.",
    )
