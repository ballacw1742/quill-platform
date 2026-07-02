"""Projects hardening — Sprint 0.2

Revision ID: 0016_projects_hardening
Revises: 0015_agent_registry_expand
Create Date: 2026-07-01

Changes:
  - projects table: add budget_usd, committed_usd, forecast_usd columns
  - New table: project_milestones
  - New table: project_log
  - New table: project_document_links
  - New table: project_contract_links
  - New table: project_estimate_links
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_projects_hardening"
down_revision = "0015_agent_registry_expand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Extend projects table ──────────────────────────────────────────────
    op.add_column("projects", sa.Column("budget_usd", sa.Float, nullable=True))
    op.add_column("projects", sa.Column("committed_usd", sa.Float, nullable=True))
    op.add_column("projects", sa.Column("forecast_usd", sa.Float, nullable=True))

    # ── project_milestones ─────────────────────────────────────────────────
    op.create_table(
        "project_milestones",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("due_date", sa.Date, nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ── project_log ────────────────────────────────────────────────────────
    op.create_table(
        "project_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("entry_type", sa.String(30), nullable=False, server_default="general"),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )

    # ── project_document_links ─────────────────────────────────────────────
    op.create_table(
        "project_document_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("document_id", sa.String(36), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.String(2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ── project_contract_links ─────────────────────────────────────────────
    op.create_table(
        "project_contract_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("contract_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ── project_estimate_links ─────────────────────────────────────────────
    op.create_table(
        "project_estimate_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("estimate_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("project_estimate_links")
    op.drop_table("project_contract_links")
    op.drop_table("project_document_links")
    op.drop_table("project_log")
    op.drop_table("project_milestones")
    op.drop_column("projects", "forecast_usd")
    op.drop_column("projects", "committed_usd")
    op.drop_column("projects", "budget_usd")
