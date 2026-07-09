"""Module configs — Modular Framework Phase 0 (MODULAR_FRAMEWORK_DESIGN.md)

Revision ID: 0026_module_configs
Revises: 0025_site_drive_intakes
Create Date: 2026-07-09

Changes:
  - New module_configs table: per-workspace enable/order overrides for the
    home-screen modules. Additive + override-only — no row means the module
    keeps its roster default (enabled), so existing tenants are unaffected.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_module_configs"
down_revision = "0025_site_drive_intakes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "module_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace", sa.String(128), nullable=False),
        sa.Column("module_key", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace", "module_key", name="uq_module_configs_ws_key"),
    )
    op.create_index(
        "ix_module_configs_workspace", "module_configs", ["workspace"]
    )


def downgrade() -> None:
    op.drop_index("ix_module_configs_workspace", table_name="module_configs")
    op.drop_table("module_configs")
