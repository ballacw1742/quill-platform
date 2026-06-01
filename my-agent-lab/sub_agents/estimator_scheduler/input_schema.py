from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class EstimatorSchedulerInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    project_label: str | None = Field(default=None, description="Input field 'project_label'")
    approved_classification: dict[str, Any] | None = Field(default=None, description="Input field 'approved_classification'")
    extracted_scope: dict[str, Any] | None = Field(default=None, description="Input field 'extracted_scope'")
    cost_library: dict[str, Any] | None = Field(default=None, description="Input field 'cost_library'")
    project_context: dict[str, Any] | None = Field(default=None, description="Input field 'project_context'")
