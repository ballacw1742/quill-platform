from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class ContractDrafterInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    mode: str | None = Field(default=None, description="Input field 'mode'")
    contract_type: str | None = Field(default=None, description="Input field 'contract_type'")
    template_id: str | None = Field(default=None, description="Input field 'template_id'")
    parties: list[dict[str, Any]] | None = Field(default=None, description="Input field 'parties'")
    effective_date: str | None = Field(default=None, description="Input field 'effective_date'")
    expiration_date: Any | None | None = Field(default=None, description="Input field 'expiration_date'")
    total_value_usd: int | None = Field(default=None, description="Input field 'total_value_usd'")
    payment_terms: dict[str, Any] | None = Field(default=None, description="Input field 'payment_terms'")
    scope_summary: str | None = Field(default=None, description="Input field 'scope_summary'")
    key_terms_requested: list[dict[str, Any]] | None = Field(default=None, description="Input field 'key_terms_requested'")
    jurisdiction: str | None = Field(default=None, description="Input field 'jurisdiction'")
    notes: str | None = Field(default=None, description="Input field 'notes'")
    prior_contract_context: Any | None | None = Field(default=None, description="Input field 'prior_contract_context'")
