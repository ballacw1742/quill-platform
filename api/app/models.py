"""SQLAlchemy 2.0 ORM models for the Approval Queue."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import get_settings
from app.db import Base
from app.enums import (
    ApprovalStatus,
    AuthMethod,
    Decision,
    ExecutionResult,
    Lane,
    Priority,
    TargetSystem,
    TrustTier,
    UserRole,
)

_settings = get_settings()

# Use JSON for SQLite compatibility, JSONB for Postgres.
if _settings.is_sqlite:
    JSONType = JSON
else:
    from sqlalchemy.dialects.postgresql import JSONB  # type: ignore

    JSONType = JSONB  # type: ignore[assignment]


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# ApprovalItem
# ---------------------------------------------------------------------------
class ApprovalItem(Base):
    __tablename__ = "approval_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    # Origin
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_version: Mapped[str] = mapped_column(String(32), default="0.0.0")
    workflow: Mapped[str] = mapped_column(String(128), index=True)

    # Routing / lane
    lane: Mapped[int] = mapped_column(Integer, index=True, default=Lane.SINGLE.value)
    priority: Mapped[str] = mapped_column(String(32), default=Priority.NORMAL.value, index=True)
    target_system: Mapped[str] = mapped_column(String(32), default=TargetSystem.NONE.value)
    api_call: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Timing
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Proposed action
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    source_artifacts: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    citations: Mapped[list[Any]] = mapped_column(JSONType, default=list)

    # Agent context
    agent_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    agent_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    agent_prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # State
    status: Mapped[str] = mapped_column(String(32), default=ApprovalStatus.PENDING.value, index=True)
    required_approvers: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    execution_result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Audit chain
    audit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prev_audit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Litigation
    litigation_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    suspended_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    records: Mapped[list[ApprovalRecord]] = relationship(
        "ApprovalRecord",
        back_populates="approval_item",
        cascade="all, delete-orphan",
        order_by="ApprovalRecord.timestamp",
    )

    __table_args__ = (
        Index("ix_approval_items_status_lane", "status", "lane"),
        Index("ix_approval_items_status_sla", "status", "sla_due_at"),
        Index("ix_approval_items_agent_status", "agent_id", "status"),
    )


# ---------------------------------------------------------------------------
# ApprovalRecord — every human decision on an item
# ---------------------------------------------------------------------------
class ApprovalRecord(Base):
    __tablename__ = "approval_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    approval_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("approval_items.id", ondelete="CASCADE"), index=True
    )
    approver_id: Mapped[str] = mapped_column(String(36), index=True)
    approver_role: Mapped[str] = mapped_column(String(32))
    decision: Mapped[str] = mapped_column(String(32))
    edits: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_method: Mapped[str] = mapped_column(String(32), default=AuthMethod.DEV_TOKEN.value)
    auth_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)

    approval_item: Mapped[ApprovalItem] = relationship("ApprovalItem", back_populates="records")


# ---------------------------------------------------------------------------
# AuditLogEntry — append-only chain
# ---------------------------------------------------------------------------
class AuditLogEntry(Base):
    __tablename__ = "audit_log_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(128), index=True)
    approval_item_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    hash: Mapped[str] = mapped_column(String(64), index=True)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_audit_chain", "approval_item_id", "id"),
    )


# ---------------------------------------------------------------------------
# AuditChainVerification — nightly + ad-hoc chain verification results
# ---------------------------------------------------------------------------
class AuditChainVerification(Base):
    __tablename__ = "audit_chain_verifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # "global" | "per_approval" | "range"
    scope: Mapped[str] = mapped_column(String(32), index=True, default="global")
    scope_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # ok | postgres_drift | b2_drift | mismatch | missing | running | error
    result: Mapped[str] = mapped_column(String(32), index=True, default="running")
    chain_length_postgres: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chain_length_mirror: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_hash_postgres: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_hash_mirror: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    triggered_by: Mapped[str] = mapped_column(String(64), default="cron")

    __table_args__ = (
        Index("ix_audit_verifications_started", "started_at"),
        Index("ix_audit_verifications_result", "result"),
    )


# ---------------------------------------------------------------------------
# AuditMirrorClaim — multi-replica claim table (Sprint 4 fix #8)
# ---------------------------------------------------------------------------
class AuditMirrorClaim(Base):
    __tablename__ = "audit_mirror_claims"

    hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    replica_id: Mapped[str] = mapped_column(
        String(128), default="unknown", server_default="unknown"
    )
    seq: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------------------
# AgentRegistration — per-agent trust + budget
# ---------------------------------------------------------------------------
class AgentRegistration(Base):
    __tablename__ = "agent_registrations"

    agent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str] = mapped_column(String(32), default="0.0.0")
    trust_tier: Mapped[str] = mapped_column(String(32), default=TrustTier.TIER_0.value)
    default_lane: Mapped[int] = mapped_column(Integer, default=Lane.SINGLE.value)
    monthly_token_budget: Mapped[int] = mapped_column(Integer, default=1_000_000)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32), default=UserRole.OBSERVER.value)
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    credentials: Mapped[list[WebAuthnCredential]] = relationship(
        "WebAuthnCredential", back_populates="user", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# WebAuthnCredential
# ---------------------------------------------------------------------------
class WebAuthnCredential(Base):
    __tablename__ = "webauthn_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # base64url-encoded credential id (no padding)
    credential_id_b64: Mapped[str] = mapped_column(String(512), index=True)
    # base64-encoded COSE public key as returned by the webauthn library
    public_key_b64: Mapped[str] = mapped_column(Text)
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    # Friendly nickname ("Charles' iPhone", "YubiKey 5C")
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # CSV of transport hints from the authenticator ("internal,hybrid", "usb,nfc")
    transports: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # "platform" (Touch ID/Face ID) vs "cross-platform" (security key)
    attachment: Mapped[str | None] = mapped_column(String(32), nullable=True)
    aaguid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    backup_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    backup_state: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="credentials")

    __table_args__ = (UniqueConstraint("credential_id_b64", name="uq_webauthn_credential_id"),)


# ---------------------------------------------------------------------------
# Document — Phase D.1 Documents service
# ---------------------------------------------------------------------------
class Document(Base):
    """A persisted artifact produced by a PM agent and approved for publication.

    Wire/DB shape mirrors web/DOCUMENTS_SPEC.md §"DB schema" (the authoritative
    spec). On Postgres, `search_vector` is a generated tsvector column with a
    GIN index; on SQLite (dev) it is omitted and search falls back to LIKE.
    """

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    # Identity / origin
    artifact_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    artifact_type: Mapped[str] = mapped_column(String(64), index=True)

    # Display
    title: Mapped[str] = mapped_column(String(256))
    summary: Mapped[str] = mapped_column(String(512), default="")
    body_markdown: Mapped[str] = mapped_column(Text, default="")

    # Producer
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_display_name: Mapped[str] = mapped_column(String(128), default="")

    # Lifecycle
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approval_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("approval_items.id", ondelete="SET NULL"), nullable=True
    )

    # Tags + storage refs
    tags: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    drive_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    minio_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Full artifact payload (Sprint G.7).
    # Named `meta` because `metadata` is reserved by SQLAlchemy DeclarativeBase
    # (it is the class-level MetaData object). The DB column is named "metadata".
    meta: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONType, default=None, nullable=True
    )

    __table_args__ = (
        Index("ix_documents_artifact_type_created", "artifact_type", "created_at"),
        Index("ix_documents_agent_created", "agent_id", "created_at"),
    )


# ---------------------------------------------------------------------------
# Estimate — Phase G.1 (drawing-driven estimate + schedule)
# ---------------------------------------------------------------------------
class Estimate(Base):
    """A drawing-upload run that flows through extraction → classification
    → estimating. Tracks the upload identity, the file manifest, and
    pointers to the resulting Documents (when each artifact is approved).

    State machine:
        queued → extracting → classifying → estimating → done
                                                          ↓
                                                       failed
    """

    __tablename__ = "estimates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    upload_id: Mapped[str] = mapped_column(
        String(36), unique=True, index=True, default=_uuid
    )
    project_label: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    """queued | extracting | classifying | estimating | done | failed"""

    # Manifest of files uploaded for this estimate — list of
    # { filename, kind, size_bytes, extraction_status, extraction_summary,
    #   minio_key }.
    uploaded_files: Mapped[list[Any]] = mapped_column(JSONType, default=list)

    # Pointers to the published Documents (set after each artifact is
    # approved + executed via approvals.execute_approval).
    classification_artifact_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    package_artifact_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    # Lifecycle
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_estimates_status_created", "status", "created_at"),
    )


# ---------------------------------------------------------------------------
# CostLibraryRow — Phase G.1 (bootstrap loader)
# ---------------------------------------------------------------------------
class CostLibraryRow(Base):
    """Flattened cost library row for fast estimator lookup.

    The authoritative library lives in agentic-pmo-prompts/data/
    cost_library_v0_1.json. The bootstrap script
    (api/scripts/bootstrap_cost_library.py) loads it into this table at
    deploy time.
    """

    __tablename__ = "cost_library_rows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    library_version: Mapped[str] = mapped_column(String(32), index=True)
    csi_section: Mapped[str] = mapped_column(String(16), index=True)
    description: Mapped[str] = mapped_column(String(300))
    unit: Mapped[str] = mapped_column(String(8))
    unit_rate_usd: Mapped[float] = mapped_column(Float)
    rate_source: Mapped[str] = mapped_column(String(32))
    rate_year: Mapped[int] = mapped_column(Integer)
    geographic_multiplier_for: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "library_version", "csi_section", "description",
            name="uq_costlib_version_section_desc",
        ),
        Index("ix_costlib_version_csi", "library_version", "csi_section"),
    )


# ---------------------------------------------------------------------------
# Contract — Sprint Contracts.1
# ---------------------------------------------------------------------------
class Contract(Base):
    """A contract document upload that flows through extraction → field-extraction
    → (Contracts.2) review.

    State machine:
        uploaded → extracting → extracted → reviewing → reviewed → drafting → drafted
                                                                              ↓
                                                                           failed
    """

    __tablename__ = "contracts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    upload_id: Mapped[str] = mapped_column(
        String(36), unique=True, index=True, default=_uuid
    )
    project_label: Mapped[str] = mapped_column(String(200), default="")
    contract_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """owner_gc | subcontract | change_order | purchase_order | letter_of_intent
       | nda | msa | equipment_lease | insurance_certificate | lien_waiver
       | other | unknown
    """

    status: Mapped[str] = mapped_column(String(32), default="uploaded", index=True)
    """uploaded | extracting | extracted | reviewing | reviewed | drafting | drafted | failed"""

    source: Mapped[str] = mapped_column(String(16), default="upload")
    """'upload' | 'drafted' (from Contracts.3)"""

    # Manifest of uploaded files — same shape as Estimate.uploaded_files:
    # [{filename, kind, size_bytes, minio_key, extraction_status, extraction_summary}]
    uploaded_files: Mapped[list[Any]] = mapped_column(JSONType, default=list)

    # Structured fields produced by contract-extractor (Contracts.1 agent)
    extracted_fields: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)

    # Denormalized for fast filter/search: [{role, name, address}]
    parties: Mapped[list[Any]] = mapped_column(JSONType, default=list)

    effective_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expiration_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    from sqlalchemy import Numeric as _Numeric
    total_value_usd: Mapped[float | None] = mapped_column(
        _Numeric(precision=18, scale=2), nullable=True
    )

    notes: Mapped[str] = mapped_column(Text, default="")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pointers to published artifacts (set in Contracts.2)
    classification_artifact_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    review_artifact_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )

    # Contracts.3 — drafter workflow
    draft_request: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    draft_artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Lifecycle
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        Index("ix_contracts_status_created", "status", "created_at"),
        Index("ix_contracts_type_created", "contract_type", "created_at"),
    )


# ---------------------------------------------------------------------------
# ContractInterpretation — Contracts.2
# Stores each Q&A pair from the /interpret endpoint.
# ---------------------------------------------------------------------------
class ContractInterpretation(Base):
    """A single plain-English Q&A exchange about a contract clause."""

    __tablename__ = "contract_interpretations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    contract_upload_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contracts.upload_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    asked_by: Mapped[str] = mapped_column(String(100), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

    __table_args__ = (
        Index("ix_contract_interp_upload_created", "contract_upload_id", "created_at"),
    )


# Import dev-chat models to ensure they're registered with Base.metadata
# before any create_all call (tests and migrations both need this).
from app.models_dev_chat import DevChatThread, DevChatMessage, DevChatTask  # noqa: F401, E402

__all__ = [
    "ApprovalItem",
    "ApprovalRecord",
    "AuditLogEntry",
    "AuditChainVerification",
    "AuditMirrorClaim",
    "AgentRegistration",
    "User",
    "WebAuthnCredential",
    "Document",
    "Estimate",
    "CostLibraryRow",
    "Decision",
    "ExecutionResult",
    "Contract",
    "ContractInterpretation",
]
