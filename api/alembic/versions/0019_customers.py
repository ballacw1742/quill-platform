"""Customer Success — Sprint 2A

Revision ID: 0019_customers
Revises: 0018_pipeline
Create Date: 2026-07-02

Changes:
  - New table: support_tickets
  - New table: account_notes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_customers"
down_revision = "0018_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── support_tickets ───────────────────────────────────────────────────────
    op.create_table(
        "support_tickets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("severity", sa.String(10), nullable=False, server_default="P3"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("resolution_notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_support_tickets_account_id", "support_tickets", ["account_id"])
    op.create_index("ix_support_tickets_status", "support_tickets", ["status"])
    op.create_index("ix_support_tickets_created_at", "support_tickets", ["created_at"])

    # ── account_notes ─────────────────────────────────────────────────────────
    op.create_table(
        "account_notes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_account_notes_account_id", "account_notes", ["account_id"])
    op.create_index("ix_account_notes_created_at", "account_notes", ["created_at"])


def downgrade() -> None:
    op.drop_table("account_notes")
    op.drop_table("support_tickets")
