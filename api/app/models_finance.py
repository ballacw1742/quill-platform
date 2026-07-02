"""ORM models for Quill Finance — Sprint 3A."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


# Valid category values for budget lines
VALID_BUDGET_CATEGORIES = (
    "land", "construction", "equipment", "opex", "contingency", "other"
)

# Valid status values for invoices
VALID_INVOICE_STATUSES = (
    "draft", "sent", "paid", "overdue", "cancelled"
)


class BudgetLine(Base):
    """A budget line item attached to a project.

    Tracks planned vs. committed vs. actual spend by category so PMs can
    identify variances before they blow the overall project budget.
    """

    __tablename__ = "budget_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True
    )  # soft FK to projects table
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # land | construction | equipment | opex | contingency | other
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    budget_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    committed_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    actual_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    period: Mapped[Optional[str]] = mapped_column(
        String(7), nullable=True
    )  # YYYY-MM format
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class Invoice(Base):
    """An invoice in the AR (accounts receivable) ledger.

    Tracks amounts owed by hyperscale customers for TPU compute capacity.
    Aging buckets (current / 30 / 60 / 90+ days) surface collection risks.
    """

    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True
    )  # soft FK to accounts table
    deal_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True
    )  # soft FK to deals table
    invoice_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    amount_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="draft", index=True
    )  # draft | sent | paid | overdue | cancelled
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    paid_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
