"""Pydantic v2 request/response schemas. Mirror the wire contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.enums import (
    Decision,
    Lane,
    Priority,
    TargetSystem,
    TrustTier,
    UserRole,
)


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


# ---------------------------------------------------------------------------
# Approval — agent-facing create payload
# ---------------------------------------------------------------------------
class Citation(_Base):
    source_type: str
    source_id: str
    excerpt: str | None = None


class SourceArtifact(_Base):
    kind: str
    ref: str
    excerpt: str | None = None


class ApprovalCreate(_Base):
    """What an agent POSTs to /v1/approvals."""

    agent_id: str = Field(..., min_length=1, max_length=64)
    agent_version: str = Field(default="0.0.0", max_length=32)
    workflow: str = Field(..., min_length=1, max_length=128)

    lane: Lane = Field(default=Lane.SINGLE)
    priority: Priority = Field(default=Priority.NORMAL)

    target_system: TargetSystem = Field(default=TargetSystem.NONE)
    api_call: str | None = None

    payload: dict[str, Any] = Field(default_factory=dict)
    source_artifacts: list[SourceArtifact] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)

    agent_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    agent_reasoning: str | None = None
    agent_model: str | None = None
    agent_prompt_version: str | None = None
    agent_input_hash: str | None = None
    agent_output_hash: str | None = None

    required_approvers: list[str] = Field(
        default_factory=list,
        description="Roles required (e.g. ['owner'] for Lane 2, ['owner', 'partner'] for Lane 3).",
    )
    expires_at: datetime | None = None


class ApprovalRecordOut(_Base):
    id: str
    approver_id: str
    approver_role: str
    decision: str
    edits: dict[str, Any] | None = None
    rejection_reason: str | None = None
    auth_method: str
    timestamp: datetime


class ApprovalOut(_Base):
    id: str
    agent_id: str
    agent_version: str
    workflow: str

    lane: int
    priority: str
    target_system: str
    api_call: str | None = None

    created_at: datetime
    sla_due_at: datetime | None = None
    expires_at: datetime | None = None
    executed_at: datetime | None = None

    payload: dict[str, Any]
    source_artifacts: list[Any]
    citations: list[Any]

    agent_confidence: float
    agent_reasoning: str | None = None
    agent_model: str | None = None
    agent_prompt_version: str | None = None

    status: str
    required_approvers: list[str]
    execution_result: str | None = None
    external_ref: str | None = None

    audit_hash: str | None = None
    prev_audit_hash: str | None = None
    litigation_hold: bool
    suspended_reason: str | None = None

    records: list[ApprovalRecordOut] = Field(default_factory=list)


class ApprovalListPage(_Base):
    items: list[ApprovalOut]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------
class DecisionRequest(_Base):
    decision: Decision
    edits: dict[str, Any] | None = None
    rejection_reason: str | None = None
    auth_assertion: str | None = Field(
        default=None,
        description="Sprint 1: opaque dev token. Sprint 2: WebAuthn assertion JSON.",
    )
    escalate_to_lane: int | None = Field(default=None, ge=1, le=3)


class CancelRequest(_Base):
    reason: str | None = None


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
class AuditEntryOut(_Base):
    id: int
    event_type: str
    actor: str
    approval_item_id: str | None = None
    payload: dict[str, Any]
    timestamp: datetime
    hash: str
    prev_hash: str | None = None


class AuditVerifyResult(_Base):
    ok: bool
    chain_length: int
    last_hash: str | None = None
    failures: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
class AgentOut(_Base):
    agent_id: str
    version: str
    trust_tier: str
    default_lane: int
    monthly_token_budget: int
    enabled: bool
    notes: str | None = None


class AgentUpdate(_Base):
    version: str | None = None
    trust_tier: TrustTier | None = None
    default_lane: Lane | None = None
    monthly_token_budget: int | None = Field(default=None, ge=0)
    enabled: bool | None = None
    notes: str | None = None


class HealthOut(_Base):
    ok: bool
    db: Literal["ok", "fail"]
    queue_depth_pending: int
    queue_depth_executed: int
    audit_chain: Literal["ok", "broken", "empty"]
    audit_chain_length: int
    sla_breaches_open: int
    version: str


class LitigationHoldRequest(_Base):
    reason: str = Field(..., min_length=3)


# ---------------------------------------------------------------------------
# Auth — email/password (dev fallback) + WebAuthn passkeys
# ---------------------------------------------------------------------------
class RegisterRequest(_Base):
    email: str
    display_name: str
    password: str = Field(..., min_length=8)
    role: UserRole = Field(default=UserRole.OBSERVER)


class LoginRequest(_Base):
    email: str
    password: str


class TokenOut(_Base):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user_id: str
    role: str


class UserOut(_Base):
    id: str
    email: str
    display_name: str
    role: str
    telegram_chat_id: str | None = None
    created_at: datetime


# ── WebAuthn ────────────────────────────────────────────────────────────────
class PasskeyRegisterBegin(_Base):
    """Optional UI hint: 'platform' or 'cross-platform'."""

    attachment: Literal["platform", "cross-platform"] | None = None
    name: str | None = Field(default=None, max_length=128)


class PasskeyOptionsOut(_Base):
    """What the browser feeds to @simplewebauthn/browser."""

    ceremony_id: str
    options: dict[str, Any]


class PasskeyRegisterComplete(_Base):
    ceremony_id: str
    response: dict[str, Any]
    name: str | None = Field(default=None, max_length=128)


class PasskeyLoginBegin(_Base):
    email: str


class PasskeyLoginComplete(_Base):
    ceremony_id: str
    response: dict[str, Any]


class ActionIntent(_Base):
    """What the user is about to authorize. Bound into the action JWT."""

    approval_id: str
    decision: Decision
    edits: dict[str, Any] | None = None
    rejection_reason: str | None = None
    escalate_to_lane: int | None = Field(default=None, ge=1, le=3)


class PasskeyChallengeBegin(_Base):
    action_intent: ActionIntent


class PasskeyChallengeComplete(_Base):
    ceremony_id: str
    response: dict[str, Any]
    action_intent: ActionIntent


class ActionAssertionOut(_Base):
    auth_assertion: str
    expires_in: int


class PasskeyCredentialOut(_Base):
    id: str
    name: str | None = None
    transports: str | None = None
    attachment: str | None = None
    aaguid: str | None = None
    backup_eligible: bool
    backup_state: bool
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


__all__ = [
    "ApprovalCreate",
    "ApprovalOut",
    "ApprovalListPage",
    "ApprovalRecordOut",
    "DecisionRequest",
    "CancelRequest",
    "AuditEntryOut",
    "AuditVerifyResult",
    "AgentOut",
    "AgentUpdate",
    "HealthOut",
    "LitigationHoldRequest",
    "RegisterRequest",
    "LoginRequest",
    "TokenOut",
    "UserOut",
    "PasskeyRegisterBegin",
    "PasskeyRegisterComplete",
    "PasskeyOptionsOut",
    "PasskeyLoginBegin",
    "PasskeyLoginComplete",
    "PasskeyChallengeBegin",
    "PasskeyChallengeComplete",
    "ActionIntent",
    "ActionAssertionOut",
    "PasskeyCredentialOut",
]
