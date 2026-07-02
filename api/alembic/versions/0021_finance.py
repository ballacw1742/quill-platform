"""Finance — Sprint 3A

Revision ID: 0021_finance
Revises: 0020_supply_chain
Create Date: 2026-07-02

Changes:
  - New table: budget_lines
  - New table: invoices
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_finance"
down_revision = "0020_supply_chain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── budget_lines ──────────────────────────────────────────────────────────
    op.create_table(
        "budget_lines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=True, index=True),
        sa.Column("category", sa.String(50), nullable=False, index=True),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("budget_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("committed_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("actual_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("period", sa.String(7), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            index=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ── invoices ──────────────────────────────────────────────────────────────
    op.create_table(
        "invoices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), nullable=True, index=True),
        sa.Column("deal_id", sa.String(36), nullable=True, index=True),
        sa.Column("invoice_number", sa.String(100), nullable=True),
        sa.Column("amount_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft", index=True),
        sa.Column("issue_date", sa.Date, nullable=False),
        sa.Column("due_date", sa.Date, nullable=False),
        sa.Column("paid_date", sa.Date, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            index=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("invoices")
    op.drop_table("budget_lines")
