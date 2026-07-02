"""ORM models for Quill Sales & Pipeline — Sprint 1B."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


# Valid account type values
VALID_ACCOUNT_TYPES = ("prospect", "customer")

# Valid deal stage values
VALID_DEAL_STAGES = ("prospect", "qualified", "proposal", "negotiating", "won", "lost")

# Valid workload types
VALID_WORKLOAD_TYPES = ("ai_hpc", "hyperscale", "enterprise_colo", "edge", "mixed")

# Valid activity types
VALID_ACTIVITY_TYPES = ("call", "email", "meeting", "proposal_sent", "contract_sent", "note")


class Account(Base):
    """A sales account — starts as prospect, becomes customer when deal is Won."""

    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="prospect", index=True
    )  # prospect | customer
    industry: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    hq_city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    hq_state: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    primary_contact_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    primary_contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    primary_contact_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class Deal(Base):
    """A sales deal — tracks TPU capacity opportunities through the pipeline."""

    __tablename__ = "deals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    stage: Mapped[str] = mapped_column(
        String(30), nullable=False, default="prospect", index=True
    )  # prospect | qualified | proposal | negotiating | won | lost
    value_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mw_required: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    workload_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # ai_hpc | hyperscale | enterprise_colo | edge | mixed
    probability_pct: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    expected_close: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    campus_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    # soft FK to campuses once won
    project_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    # soft FK to projects
    lost_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class DealActivity(Base):
    """A logged activity on a deal."""

    __tablename__ = "deal_activities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    deal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("deals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    activity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # call | email | meeting | proposal_sent | contract_sent | note
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
