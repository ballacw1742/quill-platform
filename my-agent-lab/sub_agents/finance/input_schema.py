from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field


class FinanceInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    query: str = Field(..., description="Natural-language question about ARR, invoices, cash position, capex, or budget vs actuals.")
