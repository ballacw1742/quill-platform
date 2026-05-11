"""Contract interpretations table — Sprint Contracts.2

Revision ID: 0011_contract_interpretations
Revises: 0010_contracts
Create Date: 2026-05-11

Adds ``contract_interpretations`` table to store each Q&A exchange from
the synchronous ``/v1/contracts/{upload_id}/interpret`` endpoint.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_contract_interpretations"
down_revision = "0010_contracts"
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
        "contract_interpretations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "contract_upload_id",
            sa.String(36),
            sa.ForeignKey("contracts.upload_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("answer_json", json_t, nullable=False),
        sa.Column("asked_by", sa.String(100), nullable=False, server_default="system"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_index(
        "ix_contract_interp_upload_id",
        "contract_interpretations",
        ["contract_upload_id"],
    )
    op.create_index(
        "ix_contract_interp_upload_created",
        "contract_interpretations",
        ["contract_upload_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_contract_interp_upload_created", "contract_interpretations")
    op.drop_index("ix_contract_interp_upload_id", "contract_interpretations")
    op.drop_table("contract_interpretations")
