"""Account ↔ Campus link — Sprint 5.1

Revision ID: 0023_account_campus_link
Revises: 0022_compliance
Create Date: 2026-07-05

Changes:
  - Add nullable campus_id (soft FK → campuses.id) to accounts table
    so a customer account can be linked to the campus that serves it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_account_campus_link"
down_revision = "0022_compliance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("campus_id", sa.String(36), nullable=True),
    )
    op.create_index("ix_accounts_campus_id", "accounts", ["campus_id"])


def downgrade() -> None:
    op.drop_index("ix_accounts_campus_id", table_name="accounts")
    op.drop_column("accounts", "campus_id")
