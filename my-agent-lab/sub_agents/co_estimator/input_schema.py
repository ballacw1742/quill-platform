"""Input schema for the co_estimator (Change Order Estimator) agent."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CcbPacketRef(BaseModel):
    """Embedded CCB packet — must match the structure produced by ccb_prep."""
    model_config = ConfigDict(extra="allow")

    artifact_type: str = Field(default="ccb_packet")
    metadata: dict[str, Any] = Field(
        ...,
        description="Full CCB packet metadata dict as produced by the ccb_prep agent.",
    )
    disclaimer: str | None = Field(default=None)


class CoEstimatorInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    ccb_packet_id: str = Field(
        ...,
        description="The change_id from the CCB packet this CO is based on (e.g. 'CCB-2024-001').",
    )
    ccb_packet: CcbPacketRef = Field(
        ...,
        description="The full CCB packet artifact produced by ccb_prep.",
    )
    cost_library_reference: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional cost rate library keyed by CSI division (e.g. {'03': {'unit': 'CY', 'rate_usd': 450.0}}). "
            "If omitted, the agent derives costs from context and engineering judgment."
        ),
    )
    contractor_markup_pct: float = Field(
        default=10.0,
        description="Contractor overhead and profit markup as a percentage of direct costs.",
    )
    bonding_insurance_pct: float = Field(
        default=2.5,
        description="Bonding and insurance as a percentage of direct costs.",
    )
