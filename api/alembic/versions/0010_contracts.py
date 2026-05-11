"""Contracts table — Sprint Contracts.1

Revision ID: 0010_contracts
Revises: 0009_dev_chat
Create Date: 2026-05-11

Creates the ``contracts`` table to track the upload/extraction lifecycle
for construction contract documents.

State machine:
    uploaded → extracting → extracted → reviewing → reviewed → drafting → drafted
                                                                         ↓
                                                                       failed
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_contracts"
down_revision = "0009_dev_chat"
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
        "contracts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("upload_id", sa.String(36), nullable=False, unique=True),
        sa.Column("project_label", sa.String(200), nullable=False, server_default=""),
        sa.Column("contract_type", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="uploaded"),
        sa.Column("source", sa.String(16), nullable=False, server_default="upload"),
        sa.Column("uploaded_files", json_t, nullable=True),
        sa.Column("extracted_fields", json_t, nullable=True),
        sa.Column("parties", json_t, nullable=True),
        sa.Column("effective_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expiration_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_value_usd", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("notes", sa.Text, nullable=True, server_default=""),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("classification_artifact_id", sa.String(36), nullable=True),
        sa.Column("review_artifact_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_index("ix_contracts_status_created_at", "contracts", ["status", "created_at"])
    op.create_index("ix_contracts_contract_type_created_at", "contracts", ["contract_type", "created_at"])
    op.create_index("ix_contracts_upload_id", "contracts", ["upload_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_contracts_upload_id", table_name="contracts")
    op.drop_index("ix_contracts_contract_type_created_at", table_name="contracts")
    op.drop_index("ix_contracts_status_created_at", table_name="contracts")
    op.drop_table("contracts")
