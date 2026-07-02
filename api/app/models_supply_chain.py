"""ORM models for Quill Supply Chain — Sprint 2B."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


# Valid category values for equipment
VALID_EQUIPMENT_CATEGORIES = (
    "generator", "ups", "switchgear", "cooling", "pdu", "security", "fiber", "other"
)

# Valid status values for equipment
VALID_EQUIPMENT_STATUSES = (
    "not_ordered", "ordered", "in_transit", "received", "installed", "cancelled"
)

# Valid category values for vendors
VALID_VENDOR_CATEGORIES = (
    "generator", "ups", "switchgear", "cooling", "pdu", "security", "fiber",
    "construction", "other"
)


class Equipment(Base):
    """A piece of equipment in procurement for a construction project.

    Long-lead items (generators, switchgear) are the #1 cause of construction
    schedule slippage. This model tracks procurement status so risks surface early.
    """

    __tablename__ = "equipment"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True
    )  # soft FK to projects table
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # generator | ups | switchgear | cooling | pdu | security | fiber | other
    manufacturer: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    model_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lead_time_weeks: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    order_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    expected_delivery: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    actual_delivery: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="not_ordered", index=True
    )  # not_ordered | ordered | in_transit | received | installed | cancelled
    vendor_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True
    )  # soft FK to vendors table
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class Vendor(Base):
    """A vendor or supplier in the supply chain network.

    Tracks prequalification status, performance scores, and contact information
    to help project teams find approved suppliers quickly.
    """

    __tablename__ = "vendors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # generator | ups | switchgear | cooling | pdu | security | fiber | construction | other
    contact_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    prequalified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    performance_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-10
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
