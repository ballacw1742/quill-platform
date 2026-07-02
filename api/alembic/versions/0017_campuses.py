"""Facility Operations — Campus, Incidents, Metrics — Sprint 1A

Revision ID: 0017_campuses
Revises: 0016_projects_hardening
Create Date: 2026-07-02

Changes:
  - New table: campuses
  - New table: campus_incidents
  - New table: campus_metrics
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_campuses"
down_revision = "0016_projects_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── campuses ───────────────────────────────────────────────────────────
    op.create_table(
        "campuses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=True, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("mw_capacity", sa.Float, nullable=True),
        sa.Column("mw_live", sa.Float, nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="commissioning"),
        sa.Column("pue_target", sa.Float, nullable=True),
        sa.Column("pue_current", sa.Float, nullable=True),
        sa.Column("uptime_pct", sa.Float, nullable=True),
        sa.Column("power_mw_current", sa.Float, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_campuses_status", "campuses", ["status"])

    # ── campus_incidents ───────────────────────────────────────────────────
    op.create_table(
        "campus_incidents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "campus_id",
            sa.String(36),
            sa.ForeignKey("campuses.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("severity", sa.String(5), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("impact", sa.Text, nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rca_notes", sa.Text, nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_campus_incidents_status", "campus_incidents", ["status"])

    # ── campus_metrics ─────────────────────────────────────────────────────
    op.create_table(
        "campus_metrics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "campus_id",
            sa.String(36),
            sa.ForeignKey("campuses.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("metric_type", sa.String(50), nullable=False, index=True),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("unit", sa.String(20), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("campus_metrics")
    op.drop_table("campus_incidents")
    op.drop_index("ix_campuses_status", "campuses")
    op.drop_table("campuses")
