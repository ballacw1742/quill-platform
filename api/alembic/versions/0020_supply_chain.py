"""Supply Chain — Sprint 2B

Revision ID: 0020_supply_chain
Revises: 0018_pipeline
Create Date: 2026-07-02

NOTE: This migration chains off 0018_pipeline (not 0019_customers) because
Sprint 2A (customer success / 0019) is running in parallel and has not yet
been merged. When Sprint 2A merges, the orchestrator should set the
down_revision of whichever migration runs second to point at the other one.
Severity: (invisible) — no user-visible impact; needs orchestrator adjudication
at merge time.

Changes:
  - New table: equipment
  - New table: vendors
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_supply_chain"
down_revision = "0018_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── vendors ───────────────────────────────────────────────────────────────
    # Create vendors first so equipment can soft-reference vendor_id
    op.create_table(
        "vendors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("contact_phone", sa.String(50), nullable=True),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("prequalified", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("performance_score", sa.Float, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_vendors_name", "vendors", ["name"])
    op.create_index("ix_vendors_category", "vendors", ["category"])
    op.create_index("ix_vendors_prequalified", "vendors", ["prequalified"])
    op.create_index("ix_vendors_created_at", "vendors", ["created_at"])

    # ── equipment ─────────────────────────────────────────────────────────────
    op.create_table(
        "equipment",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("manufacturer", sa.String(255), nullable=True),
        sa.Column("model_number", sa.String(100), nullable=True),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="1"),
        sa.Column("unit_cost_usd", sa.Float, nullable=True),
        sa.Column("lead_time_weeks", sa.Integer, nullable=True),
        sa.Column("order_date", sa.Date, nullable=True),
        sa.Column("expected_delivery", sa.Date, nullable=True),
        sa.Column("actual_delivery", sa.Date, nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="not_ordered"),
        sa.Column("vendor_id", sa.String(36), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_equipment_project_id", "equipment", ["project_id"])
    op.create_index("ix_equipment_category", "equipment", ["category"])
    op.create_index("ix_equipment_status", "equipment", ["status"])
    op.create_index("ix_equipment_vendor_id", "equipment", ["vendor_id"])
    op.create_index("ix_equipment_created_at", "equipment", ["created_at"])


def downgrade() -> None:
    op.drop_table("equipment")
    op.drop_table("vendors")
