"""Module sub-feature toggles — Modular Framework Phase 1 (MODULAR_FRAMEWORK_DESIGN.md §3.2)

Revision ID: 0027_module_features
Revises: 0026_module_configs
Create Date: 2026-07-09

Changes:
  - Add module_configs.features JSON column: per-module sub-feature toggles
    {feature_key: bool}. Nullable + additive — a null/absent dict means all
    sub-features enabled, so existing rows are unaffected.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_module_features"
down_revision = "0026_module_configs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "module_configs",
        sa.Column("features", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("module_configs", "features")
