from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class CoordinatorOutputOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(..., description="Echo the request UUID from input.")
    intent_classification: Literal["information_query", "draft_request", "workflow_dispatch", "status_inquiry", "escalation", "administrative", "out_of_scope", "prompt_injection_suspected"] = Field(...)
    summary: str = Field(..., description="1-2 sentences plain English describing what the user is asking and what Coordinator will do.")
    dispatch_plan: list[dict[str, Any]] = Field(..., description="Sub-agent tasks to dispatch. May be empty for pure information_query.")
    direct_response: str = Field(..., description="Natural-language reply to the requester. ≤ 120 words.")
    citations: list[dict[str, Any]] = Field(..., description="Evidence for any factual claims in direct_response. Required when direct_response makes factual claims.")
    escalation_reasons: list[Literal["prompt_injection_detected", "out_of_scope", "cross_agent_dependency", "missing_context", "policy_block", "safety", "ambiguous_intent", "untrusted_submitter", "low_confidence", "exceeds_token_budget"]] = Field(...)
    confidence: float = Field(...)
    requires_charles_acknowledgment: bool = Field(...)
