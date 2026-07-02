"""Compliance Register — Sprint 4A

Revision ID: 0022_compliance
Revises: 0021_finance
Create Date: 2026-07-02

Changes:
  - New table: contract_obligations
  - New table: regulatory_items
  - New table: insurance_policies
  - New table: compliance_checklists
  - New table: compliance_checklist_items
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_compliance"
down_revision = "0021_finance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── contract_obligations ──────────────────────────────────────────────────
    op.create_table(
        "contract_obligations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("contract_id", sa.String(36), nullable=True, index=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("obligation_type", sa.String(50), nullable=False, index=True),
        sa.Column("due_date", sa.Date, nullable=True, index=True),
        sa.Column("recurrence", sa.String(20), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open", index=True),
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

    # ── regulatory_items ──────────────────────────────────────────────────────
    op.create_table(
        "regulatory_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("framework", sa.String(20), nullable=False, index=True),
        sa.Column("jurisdiction", sa.String(100), nullable=True, index=True),
        sa.Column("due_date", sa.Date, nullable=True, index=True),
        sa.Column("recurrence", sa.String(20), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open", index=True),
        sa.Column("responsible_party", sa.String(200), nullable=True),
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

    # ── insurance_policies ────────────────────────────────────────────────────
    op.create_table(
        "insurance_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("policy_name", sa.String(300), nullable=False),
        sa.Column("policy_type", sa.String(50), nullable=False, index=True),
        sa.Column("carrier", sa.String(200), nullable=True),
        sa.Column("policy_number", sa.String(100), nullable=True),
        sa.Column("coverage_amount_usd", sa.Float, nullable=True),
        sa.Column("premium_annual_usd", sa.Float, nullable=True),
        sa.Column("effective_date", sa.Date, nullable=True),
        sa.Column("expiry_date", sa.Date, nullable=True, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active", index=True),
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

    # ── compliance_checklists ─────────────────────────────────────────────────
    op.create_table(
        "compliance_checklists",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("framework", sa.String(20), nullable=False, index=True),
        sa.Column("campus_id", sa.String(36), nullable=True, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active", index=True),
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

    # ── compliance_checklist_items ────────────────────────────────────────────
    op.create_table(
        "compliance_checklist_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "checklist_id",
            sa.String(36),
            sa.ForeignKey("compliance_checklists.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("control_id", sa.String(50), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("checked", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_url", sa.String(500), nullable=True),
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
    op.drop_table("compliance_checklist_items")
    op.drop_table("compliance_checklists")
    op.drop_table("insurance_policies")
    op.drop_table("regulatory_items")
    op.drop_table("contract_obligations")
