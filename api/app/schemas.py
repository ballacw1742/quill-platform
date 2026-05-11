"""Pydantic v2 request/response schemas. Mirror the wire contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


# ---------------------------------------------------------------------------
# Documents — Phase D.1
# ---------------------------------------------------------------------------
class DocumentOut(_Base):
    id: str
    artifact_id: str
    artifact_type: str
    title: str
    summary: str
    body_markdown: str
    agent_id: str
    agent_display_name: str
    created_at: datetime
    approved_at: datetime | None = None
    approved_by: str | None = None
    approval_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    drive_url: str | None = None
    minio_path: str | None = None
    # Full artifact payload (Sprint G.7). Sourced from Document.meta column.
    # Kept out of DocumentSummary to avoid bloating list responses.
    metadata: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def _remap_meta_to_metadata(cls, data: Any) -> Any:  # noqa: ANN401
        """Bridge Document.meta (ORM attr) → DocumentOut.metadata (schema field).

        The ORM column is stored as `meta` because SQLAlchemy's DeclarativeBase
        already uses `metadata` for the class-level MetaData object. This
        validator transparently lifts it to `metadata` for API consumers.
        """
        if isinstance(data, dict):
            return data
        # ORM model instance or any object with a `meta` attribute.
        if hasattr(data, "meta"):
            # Build a plain dict from the mapper's column attributes, then
            # inject `metadata` from `meta`.
            try:
                mapper = data.__class__.__mapper__  # type: ignore[attr-defined]
                row: dict[str, Any] = {}
                for attr in mapper.column_attrs:
                    row[attr.key] = getattr(data, attr.key, None)
                # `meta` is the Python attr; `metadata` is the schema field name.
                row["metadata"] = row.pop("meta", None)
                return row
            except Exception:  # noqa: BLE001
                pass
        return data


class DocumentSummary(_Base):
    """Lightweight projection used in list/search responses."""

    id: str
    artifact_id: str
    artifact_type: str
    title: str
    summary: str
    agent_id: str
    agent_display_name: str
    created_at: datetime
    approved_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    drive_url: str | None = None


class DocumentListPage(_Base):
    items: list[DocumentSummary]
    total: int
    limit: int
    offset: int


class DocumentSearchHit(_Base):
    id: str
    artifact_id: str
    artifact_type: str
    title: str
    summary: str
    agent_id: str
    agent_display_name: str
    created_at: datetime
    snippet: str | None = None
    score: float | None = None
    tags: list[str] = Field(default_factory=list)


class DocumentSearchResult(_Base):
    items: list[DocumentSearchHit]
    total: int
    q: str


class DocumentDriveLinkOut(_Base):
    url: str | None = None
    pending: bool = False


class DocumentReindexResult(_Base):
    ok: bool
    reindexed: int
    backend: Literal["postgres-tsvector", "sqlite-like"]


# ---------------------------------------------------------------------------
# Dev Chat — Sprint DC.1
# ---------------------------------------------------------------------------

class DevChatMessageOut(_Base):
    id: str
    thread_id: str
    role: str
    content: str
    metadata: dict[str, Any] | None = Field(default=None, alias="metadata_")
    status: str
    commit_sha: str | None = None
    files_changed: list[Any] | None = None
    cost_usd: float | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class DevChatTaskOut(_Base):
    id: str
    message_id: str
    thread_id: str
    user_id: str
    branch: str
    status: str
    budget_usd_cap: float
    disallowed_paths: list[str] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


class DevChatThreadOut(_Base):
    id: str
    user_id: str
    state: str
    created_at: datetime
    updated_at: datetime


class DevChatThreadPage(_Base):
    thread: DevChatThreadOut
    messages: list[DevChatMessageOut]
    total: int
    limit: int


class DevChatSendRequest(_Base):
    content: str = Field(..., min_length=1, max_length=8000)
    auth_assertion: str | None = None


class DevChatCancelRequest(_Base):
    """Body for passkey-gated cancel endpoint."""
    auth_assertion: str | None = None


class DevChatSendResponse(_Base):
    task_id: str
    message_id: str
    thread_state: str


class DevChatStatusOut(_Base):
    state: str
    current_task_id: str | None = None
    current_message_id: str | None = None
    started_at: datetime | None = None


# ---------------------------------------------------------------------------
# Contracts — Sprint Contracts.1
# ---------------------------------------------------------------------------

_CONTRACT_DISCLAIMER = (
    "AI-generated analysis. This is not legal advice. "
    "Review with qualified counsel before relying on it for any binding decision."
)


class ContractUploadedFileEntry(_Base):
    filename: str
    kind: str
    size_bytes: int = 0
    extraction_status: str = "pending"
    extraction_summary: str = ""
    minio_key: str | None = None


class ContractListItem(_Base):
    """Lightweight projection used in list responses."""

    upload_id: str
    project_label: str = ""
    contract_type: str | None = None
    status: str
    source: str = "upload"
    effective_date: datetime | None = None
    expiration_date: datetime | None = None
    total_value_usd: float | None = None
    created_at: datetime
    updated_at: datetime
    error_message: str | None = None


class ContractOut(_Base):
    """Full contract record returned for single-resource calls."""

    upload_id: str
    project_label: str = ""
    contract_type: str | None = None
    status: str
    source: str = "upload"
    uploaded_files: list[Any] = Field(default_factory=list)
    extracted_fields: dict[str, Any] | None = None
    parties: list[Any] = Field(default_factory=list)
    effective_date: datetime | None = None
    expiration_date: datetime | None = None
    total_value_usd: float | None = None
    notes: str = ""
    error_message: str | None = None
    classification_artifact_id: str | None = None
    review_artifact_id: str | None = None
    # Contracts.3 fields
    draft_request: dict[str, Any] | None = None
    draft_artifact_id: str | None = None
    mode: str | None = None
    created_at: datetime
    updated_at: datetime
    # AI-output disclaimer — always populated programmatically
    disclaimer: str = _CONTRACT_DISCLAIMER


class ContractListPage(_Base):
    items: list[ContractListItem]
    total: int
    limit: int
    offset: int


class ContractUploadOut(_Base):
    upload_id: str
    file_count: int
    total_bytes: int
    extraction_started: bool


class ContractStatusOut(_Base):
    upload_id: str
    status: str
    contract_type: str | None = None
    effective_date: datetime | None = None
    expiration_date: datetime | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Contracts — Sprint Contracts.2
# ---------------------------------------------------------------------------

class _DispatchReviewOut(_Base):
    ok: bool
    upload_id: str
    audit_hash: str


class _InterpretRequest(_Base):
    question: str


class ContractInterpretationOut(_Base):
    """Response from POST /v1/contracts/{upload_id}/interpret."""

    contract_upload_id: str
    question: str
    answer: str
    supporting_clauses: list[Any] = Field(default_factory=list)
    confidence: float
    caveats: list[Any] = Field(default_factory=list)
    disclaimer: str = _CONTRACT_DISCLAIMER
    created_at: datetime | None = None
    interpretation_id: str | None = None


class ContractReviewSeverityCounts(_Base):
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0


class ContractReviewListItem(_Base):
    review_artifact_id: str
    created_at: datetime
    severity_counts: ContractReviewSeverityCounts


class ContractReviewListPage(_Base):
    items: list[ContractReviewListItem]
    total: int


class ContractInterpretationListPage(_Base):
    items: list[ContractInterpretationOut]
    total: int


# ---------------------------------------------------------------------------
# Contracts — Sprint Contracts.3 (drafter)
# ---------------------------------------------------------------------------

class ContractTemplateOut(_Base):
    """A single contract template's metadata (frontmatter) + body."""

    template_id: str
    contract_type: str
    display_name: str
    version: str = "0.1.0"
    required_variables: list[str] = Field(default_factory=list)
    optional_variables: list[str] = Field(default_factory=list)
    jurisdiction_notes: str = ""
    suitable_for: str = ""
    body: str = ""  # included only in single-template detail response


class ContractTemplateListResponse(_Base):
    items: list[ContractTemplateOut]
    total: int


class ContractDraftRequest(_Base):
    """Request body for POST /v1/contracts/draft."""

    mode: Literal["template", "negotiated"]
    contract_type: str
    template_id: str | None = None
    parties: list[dict[str, Any]] = Field(default_factory=list)
    effective_date: str | None = None
    expiration_date: str | None = None
    total_value_usd: float | None = None
    payment_terms: str | None = None
    scope_summary: str = ""
    key_terms_requested: list[dict[str, Any]] = Field(default_factory=list)
    jurisdiction: str = "Ohio"
    notes: str = ""
    prior_contract_upload_id: str | None = None


class _DraftSection(_Base):
    heading: str
    anchor: str
    summary: str


class _DraftAttorneyFocus(_Base):
    topic: str
    why: str
    suggested_question: str


class _DraftAssumption(_Base):
    topic: str
    assumption: str
    why_made: str


class ContractDraftMetadataOut(_Base):
    """Pydantic equivalent of contract_draft.schema.json agent output."""

    artifact_type: Literal["contract_draft"] = "contract_draft"
    contract_type: str
    mode: str
    template_id: str | None = None
    parties: list[dict[str, Any]] = Field(default_factory=list)
    effective_date: str | None = None
    expiration_date: str | None = None
    total_value_usd: float | None = None
    title: str
    summary: str
    body_markdown: str
    sections: list[_DraftSection] = Field(default_factory=list)
    variables_used: dict[str, Any] = Field(default_factory=dict)
    key_terms_addressed: dict[str, str] = Field(default_factory=dict)
    assumptions_made: list[_DraftAssumption] = Field(default_factory=list)
    attorney_review_focus: list[_DraftAttorneyFocus] = Field(default_factory=list)
    disclaimer: str = _CONTRACT_DISCLAIMER
    citations: list[Any] = Field(default_factory=list)


class RedraftRequest(_Base):
    """Body for POST /v1/contracts/{upload_id}/redraft."""

    revision_notes: str
    key_terms_overrides: list[dict[str, Any]] | None = None


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
    "DocumentOut",
    "DocumentSummary",
    "DocumentListPage",
    "DocumentSearchHit",
    "DocumentSearchResult",
    "DocumentDriveLinkOut",
    "DocumentReindexResult",
    # Contracts (Sprint Contracts.1)
    "ContractOut",
    "ContractListPage",
    "ContractListItem",
    "ContractUploadOut",
    "ContractStatusOut",
    # Contracts (Sprint Contracts.2)
    "_DispatchReviewOut",
    "_InterpretRequest",
    "ContractInterpretationOut",
    "ContractReviewSeverityCounts",
    "ContractReviewListItem",
    "ContractReviewListPage",
    "ContractInterpretationListPage",
    # Contracts (Sprint Contracts.3)
    "ContractTemplateOut",
    "ContractTemplateListResponse",
    "ContractDraftRequest",
    "ContractDraftMetadataOut",
    "RedraftRequest",
    # Dev Chat (Sprint DC.1)
    "DevChatMessageOut",
    "DevChatThreadOut",
    "DevChatTaskOut",
    "DevChatSendRequest",
    "DevChatSendResponse",
    "DevChatStatusOut",
    "DevChatThreadPage",
]
