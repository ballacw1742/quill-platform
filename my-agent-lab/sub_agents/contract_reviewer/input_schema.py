from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class ContractReviewerInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    upload_id: str | None = Field(default=None, description="Input field 'upload_id'")
    project_label: str | None = Field(default=None, description="Input field 'project_label'")
    extraction: dict[str, Any] | None = Field(default=None, description="Input field 'extraction'")
    raw_text: str | None = Field(default=None, description="Input field 'raw_text'")
    context: dict[str, Any] | None = Field(default=None, description="Input field 'context'")
