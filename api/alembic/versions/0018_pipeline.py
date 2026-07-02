"""Pipeline — Sprint 1B

Revision ID: 0018_pipeline
Revises: 0017_campuses
Create Date: 2026-07-02

Changes:
  - New table: accounts
  - New table: deals
  - New table: deal_activities
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_pipeline"
down_revision = "0017_campuses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── accounts ──────────────────────────────────────────────────────────────
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(30), nullable=False, server_default="prospect"),
        sa.Column("industry", sa.String(100), nullable=True),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("hq_city", sa.String(100), nullable=True),
        sa.Column("hq_state", sa.String(50), nullable=True),
        sa.Column("primary_contact_name", sa.String(255), nullable=True),
        sa.Column("primary_contact_email", sa.String(255), nullable=True),
        sa.Column("primary_contact_phone", sa.String(50), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_accounts_type", "accounts", ["type"])
    op.create_index("ix_accounts_created_at", "accounts", ["created_at"])

    # ── deals ─────────────────────────────────────────────────────────────────
    op.create_table(
        "deals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("stage", sa.String(30), nullable=False, server_default="prospect"),
        sa.Column("value_usd", sa.Float, nullable=True),
        sa.Column("mw_required", sa.Float, nullable=True),
        sa.Column("workload_type", sa.String(50), nullable=True),
        sa.Column("probability_pct", sa.Integer, nullable=True),
        sa.Column("expected_close", sa.Date, nullable=True),
        sa.Column("campus_id", sa.String(36), nullable=True),
        sa.Column("project_id", sa.String(36), nullable=True),
        sa.Column("lost_reason", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_deals_account_id", "deals", ["account_id"])
    op.create_index("ix_deals_stage", "deals", ["stage"])
    op.create_index("ix_deals_created_at", "deals", ["created_at"])

    # ── deal_activities ───────────────────────────────────────────────────────
    op.create_table(
        "deal_activities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "deal_id",
            sa.String(36),
            sa.ForeignKey("deals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("activity_type", sa.String(30), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_deal_activities_deal_id", "deal_activities", ["deal_id"])
    op.create_index("ix_deal_activities_created_at", "deal_activities", ["created_at"])


def downgrade() -> None:
    op.drop_table("deal_activities")
    op.drop_table("deals")
    op.drop_table("accounts")
