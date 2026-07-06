"""ORM models for Quill Facility Operations — Sprint 1A."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Campus — an operating data center facility (post-commissioning)
# ---------------------------------------------------------------------------

VALID_CAMPUS_STATUSES = ("commissioning", "live", "maintenance", "decommissioned")
VALID_METRIC_TYPES = ("pue", "uptime_pct", "power_mw", "temp_avg", "cooling_efficiency")
VALID_INCIDENT_SEVERITIES = ("P1", "P2", "P3", "P4")
VALID_INCIDENT_STATUSES = ("open", "investigating", "resolved", "closed")


class Campus(Base):
    """An operating data center campus promoted from a construction project."""

    __tablename__ = "campuses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Soft FK to projects — not enforced at DB level (project may be archived)
    project_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Power capacity
    mw_capacity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # total designed MW
    mw_live: Mapped[Optional[float]] = mapped_column(Float, nullable=True)        # currently energized MW

    # Operational status
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="commissioning", index=True
    )  # commissioning | live | maintenance | decommissioned

    # Efficiency targets + actuals
    pue_target: Mapped[Optional[float]] = mapped_column(Float, nullable=True)     # e.g. 1.2
    pue_current: Mapped[Optional[float]] = mapped_column(Float, nullable=True)    # latest reading
    uptime_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)     # rolling 30-day %
    power_mw_current: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # current draw

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


# ---------------------------------------------------------------------------
# CampusIncident — operational incidents at a campus
# ---------------------------------------------------------------------------

class CampusIncident(Base):
    """An operational incident (outage, degradation, maintenance) at a campus."""

    __tablename__ = "campus_incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    campus_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campuses.id", ondelete="CASCADE"), nullable=False, index=True
    )

    severity: Mapped[str] = mapped_column(String(5), nullable=False)   # P1 | P2 | P3 | P4
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", index=True
    )  # open | investigating | resolved | closed

    impact: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # customer-visible impact
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rca_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


# ---------------------------------------------------------------------------
# CampusMetric — time-series metric data points for a campus
# ---------------------------------------------------------------------------

class CampusMetric(Base):
    """A single metric data point for a campus (PUE, uptime, power draw, etc.)."""

    __tablename__ = "campus_metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    campus_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campuses.id", ondelete="CASCADE"), nullable=False, index=True
    )

    metric_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # pue | uptime_pct | power_mw | temp_avg | cooling_efficiency
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # "%" | "MW" | "°F"

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )


# ---------------------------------------------------------------------------
# CampusMonitoringAgent — monitoring agents registered for a campus (Sprint 5.4)
# ---------------------------------------------------------------------------

VALID_MONITORING_AGENT_STATUSES = ("registered", "active", "disabled")


class CampusMonitoringAgent(Base):
    """A monitoring agent deployed/registered for a campus.

    Created by the Sprint 5.4 campus template deployment workflow. Soft record
    of what monitoring coverage a campus has (power, cooling, security, ...).
    """

    __tablename__ = "campus_monitoring_agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    campus_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campuses.id", ondelete="CASCADE"), nullable=False, index=True
    )

    agent_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(50), nullable=False)  # power | cooling | security | network | environment
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="registered", index=True
    )  # registered | active | disabled
    endpoint_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
