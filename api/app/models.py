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


__all__ = [
    "ApprovalItem",
    "ApprovalRecord",
    "AuditLogEntry",
    "AuditChainVerification",
    "AuditMirrorClaim",
    "AgentRegistration",
    "User",
    "WebAuthnCredential",
    "Decision",
    "ExecutionResult",
]
