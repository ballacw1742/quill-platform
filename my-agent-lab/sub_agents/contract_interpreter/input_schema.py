from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class ContractInterpreterInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    contract_extraction: dict[str, Any] | None = Field(default=None, description="Input field 'contract_extraction'")
    raw_text_excerpt: str | None = Field(default=None, description="Input field 'raw_text_excerpt'")
    question: str | None = Field(default=None, description="Input field 'question'")
