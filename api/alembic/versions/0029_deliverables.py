"""Deliverables — Phase A spine (deliverable-phase-a)

Revision ID: 0029_deliverables
Revises: 0028_custom_modules
Create Date: 2026-07-09

Changes:
  - New deliverables table: live head record per deliverable artifact, versioned
    monotonically, user-scoped. project_id nullable.
  - New deliverable_versions table: immutable per-version snapshots (insert-only).
  Additive — no existing tables modified, no existing behavior changed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029_deliverables"
down_revision = "0028_custom_modules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── deliverables (live head) ──────────────────────────────────────────────
    op.create_table(
        "deliverables",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=True),
        sa.Column("module_key", sa.String(64), nullable=False),
        sa.Column("deliverable_type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("content", sa.JSON(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_deliverables_user_id", "deliverables", ["user_id"])
    op.create_index("ix_deliverables_project_id", "deliverables", ["project_id"])

    # ── deliverable_versions (immutable snapshots) ────────────────────────────
    op.create_table(
        "deliverable_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("deliverable_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("content", sa.JSON(), nullable=True),
        sa.Column("change_action", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_deliverable_versions_deliverable_id",
        "deliverable_versions",
        ["deliverable_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_deliverable_versions_deliverable_id",
        table_name="deliverable_versions",
    )
    op.drop_table("deliverable_versions")
    op.drop_index("ix_deliverables_project_id", table_name="deliverables")
    op.drop_index("ix_deliverables_user_id", table_name="deliverables")
    op.drop_table("deliverables")
