"""cost_library_rows table — Phase G.1

Revision ID: 0007_cost_library
Revises: 0006_estimates
Create Date: 2026-05-09

Flat table holding cost library rows for fast estimator lookup. The
authoritative library lives in agentic-pmo-prompts/data/
cost_library_v0_1.json. Bootstrap is via api/scripts/bootstrap_cost_library.py.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_cost_library"
down_revision = "0006_estimates"
branch_labels = None
depends_on = None


def _is_postgres(bind) -> bool:
    return bind.dialect.name == "postgresql"


def _json_type(bind):
    if _is_postgres(bind):
        from sqlalchemy.dialects.postgresql import JSONB

        return JSONB()
    return sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    json_t = _json_type(bind)

    op.create_table(
        "cost_library_rows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("library_version", sa.String(32), nullable=False),
        sa.Column("csi_section", sa.String(16), nullable=False),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("unit", sa.String(8), nullable=False),
        sa.Column("unit_rate_usd", sa.Float, nullable=False),
        sa.Column("rate_source", sa.String(32), nullable=False),
        sa.Column("rate_year", sa.Integer, nullable=False),
        sa.Column("geographic_multiplier_for", sa.String(200), nullable=True),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.5"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("tags", json_t, nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "library_version",
            "csi_section",
            "description",
            name="uq_costlib_version_section_desc",
        ),
    )

    op.create_index(
        "ix_costlib_library_version", "cost_library_rows", ["library_version"]
    )
    op.create_index(
        "ix_costlib_csi_section", "cost_library_rows", ["csi_section"]
    )
    op.create_index(
        "ix_costlib_version_csi",
        "cost_library_rows",
        ["library_version", "csi_section"],
    )


def downgrade() -> None:
    op.drop_index("ix_costlib_version_csi", table_name="cost_library_rows")
    op.drop_index("ix_costlib_csi_section", table_name="cost_library_rows")
    op.drop_index("ix_costlib_library_version", table_name="cost_library_rows")
    op.drop_table("cost_library_rows")
