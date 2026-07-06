"""Site Drive intakes — Sprint 2 (Drive document intake honesty)

Revision ID: 0025_site_drive_intakes
Revises: 0024_campus_monitoring_agents
Create Date: 2026-07-06

Changes:
  - New site_drive_intakes table: per-run, per-document Drive intake results
    so the API can report what actually happened instead of a fake "queued".
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_site_drive_intakes"
down_revision = "0024_campus_monitoring_agents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_drive_intakes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("site_id", sa.String(64), nullable=False),
        sa.Column("folder_url", sa.String(1000), nullable=False),
        sa.Column("requested_by", sa.String(36), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("documents", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_site_drive_intakes_site_id", "site_drive_intakes", ["site_id"])
    op.create_index(
        "ix_site_drive_intakes_created_at", "site_drive_intakes", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_site_drive_intakes_created_at", table_name="site_drive_intakes")
    op.drop_index("ix_site_drive_intakes_site_id", table_name="site_drive_intakes")
    op.drop_table("site_drive_intakes")
