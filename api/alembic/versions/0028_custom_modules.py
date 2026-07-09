"""Custom modules — Modular Framework Phase 3 (MODULAR_FRAMEWORK_DESIGN.md §3.4)

Revision ID: 0028_custom_modules
Revises: 0027_module_features
Create Date: 2026-07-09

Changes:
  - New custom_modules table: workspace-authored modules that extend the
    built-in roster. Additive — no builtin behavior changes.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028_custom_modules"
down_revision = "0027_module_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_modules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace", sa.String(128), nullable=False),
        sa.Column("module_key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("href", sa.String(200), nullable=False, server_default="/requests"),
        sa.Column(
            "gradient",
            sa.String(120),
            nullable=False,
            server_default="from-slate-400 to-slate-600",
        ),
        sa.Column("icon", sa.String(60), nullable=True),
        sa.Column("features", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace", "module_key", name="uq_custom_modules_ws_key"),
    )
    op.create_index(
        "ix_custom_modules_workspace", "custom_modules", ["workspace"]
    )


def downgrade() -> None:
    op.drop_index("ix_custom_modules_workspace", table_name="custom_modules")
    op.drop_table("custom_modules")
