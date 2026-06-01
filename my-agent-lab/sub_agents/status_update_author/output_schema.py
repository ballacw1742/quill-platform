from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class StatusUpdateMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., description="Project key (e.g. 'DC-OH-08' / 'QPB1'). Drives Drive folder routing and search index partition.")
    period_start: str = Field(..., description="Inclusive start date (YYYY-MM-DD) of the reporting window.")
    period_end: str = Field(..., description="Inclusive end date (YYYY-MM-DD) of the reporting window.")
    audience: Literal["owner", "partner", "internal"] = Field(..., description="Drives tone, depth of cost detail, and Lane: 'owner' forces Lane 3 (Charles approves before send), 'partner' is Lane 2, 'internal' Lane 2 default.")
    headline_status: Literal["green", "yellow", "red"] | None = Field(default=None, description="Overall project health for the period.")
    data_freshness: dict[str, Any] | None = Field(default=None, description="Recency timestamps per source. If any are older than the period_end by >48h, the agent should flag 'data_freshness_stale' in escalation_reasons.")
    sections: dict[str, Any] = Field(..., description="Structured section text. body_markdown is the rendered concatenation; these fields keep the parts addressable for downstream re-use (e.g. owner deck s")
    metrics: dict[str, Any] | None = Field(default=None, description="Optional structured metrics. Numbers shown in body_markdown SHOULD also appear here so downstream tooling can re-render without re-parsing prose.")

class StatusUpdateDraftOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifact_type: Literal["status_update"] = Field(...)
    metadata: StatusUpdateMetadata = Field(...)
