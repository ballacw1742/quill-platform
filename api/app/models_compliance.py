"""ORM models for Quill Compliance Register — Sprint 4A."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ── ContractObligation ────────────────────────────────────────────────────────

VALID_OBLIGATION_TYPES = (
    "payment", "notice", "reporting", "renewal", "termination", "other"
)
VALID_OBLIGATION_STATUSES = ("open", "complete", "overdue", "waived")
VALID_RECURRENCES = ("one_time", "monthly", "quarterly", "annual")


class ContractObligation(Base):
    """A deadline or recurring obligation derived from a contract.

    Tracks payment deadlines, notice requirements, reporting obligations,
    renewal windows, and termination rights so nothing slips through the cracks.
    """

    __tablename__ = "contract_obligations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    contract_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True
    )  # soft FK to contracts table
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    obligation_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # payment | notice | reporting | renewal | termination | other
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    recurrence: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # one_time | monthly | quarterly | annual
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", index=True
    )  # open | complete | overdue | waived
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


# ── RegulatoryItem ────────────────────────────────────────────────────────────

VALID_REGULATORY_FRAMEWORKS = (
    "ferc", "nerc", "epa", "fisma", "soc2", "iso27001", "gdpr", "ccpa", "state", "other"
)
VALID_REGULATORY_STATUSES = ("open", "complete", "in_progress", "waived")


class RegulatoryItem(Base):
    """A regulatory filing deadline or compliance requirement.

    Covers FERC/NERC reporting, EPA permits, FISMA ATOs, SOC 2 renewals,
    and state-specific filings across the portfolio.
    """

    __tablename__ = "regulatory_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    framework: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )  # ferc | nerc | epa | fisma | soc2 | iso27001 | gdpr | ccpa | state | other
    jurisdiction: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    recurrence: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # one_time | monthly | quarterly | annual
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", index=True
    )  # open | complete | in_progress | waived
    responsible_party: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


# ── InsurancePolicy ───────────────────────────────────────────────────────────

VALID_INSURANCE_TYPES = (
    "property", "casualty", "directors_officers", "cyber",
    "builders_risk", "professional", "other"
)
VALID_INSURANCE_STATUSES = ("active", "expiring", "expired", "cancelled")


class InsurancePolicy(Base):
    """An insurance policy held by the JV.

    Tracks coverage amounts, premiums, effective/expiry dates, and flags
    policies expiring within 30 days so renewals aren't missed.
    """

    __tablename__ = "insurance_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    policy_name: Mapped[str] = mapped_column(String(300), nullable=False)
    policy_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # property | casualty | directors_officers | cyber | builders_risk | professional | other
    carrier: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    policy_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    coverage_amount_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    premium_annual_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    effective_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", index=True
    )  # active | expiring | expired | cancelled
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


# ── ComplianceChecklist ───────────────────────────────────────────────────────

VALID_CHECKLIST_FRAMEWORKS = ("soc2", "iso27001", "fisma", "nist", "custom")
VALID_CHECKLIST_STATUSES = ("active", "complete", "archived")


class ComplianceChecklist(Base):
    """A compliance checklist (e.g. SOC 2 Type II, ISO 27001, FISMA ATO).

    Each checklist belongs to an optional campus and contains items (controls)
    that can be checked off as evidence is gathered.
    """

    __tablename__ = "compliance_checklists"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    framework: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )  # soc2 | iso27001 | fisma | nist | custom
    campus_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", index=True
    )  # active | complete | archived
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


# ── ComplianceChecklistItem ───────────────────────────────────────────────────

class ComplianceChecklistItem(Base):
    """A single control/item within a compliance checklist.

    Maps to a specific framework control (e.g. SOC 2 CC6.1, NIST AC-2).
    Tracks checked state, evidence URL, and notes.
    """

    __tablename__ = "compliance_checklist_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    checklist_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("compliance_checklists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    control_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    checked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
