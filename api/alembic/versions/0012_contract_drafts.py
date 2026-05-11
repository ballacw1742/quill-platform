"""Contract drafts — Sprint Contracts.3

Revision ID: 0012_contract_drafts
Revises: 0011_contract_interpretations
Create Date: 2026-05-11

Adds three nullable columns to ``contracts`` table to support the
contract-drafter workflow:

  - ``draft_request``   (JSON)    — the ContractDraftRequest payload stored at creation
  - ``draft_artifact_id`` (VARCHAR(36)) — Document.id pointing to the approved draft artifact
  - ``mode``            (VARCHAR(16)) — 'template' | 'negotiated' | NULL for uploaded contracts

Also adds a composite index on ``(source, created_at)`` for fast polling
by the contract-draft-dispatcher daemon.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_contract_drafts"
down_revision = "0011_contract_interpretations"
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

    # draft_request: JSON blob of the ContractDraftRequest
    op.add_column(
        "contracts",
        sa.Column("draft_request", json_t, nullable=True),
    )

    # draft_artifact_id: pointer to the Document once the draft is approved
    op.add_column(
        "contracts",
        sa.Column("draft_artifact_id", sa.String(36), nullable=True),
    )

    # mode: 'template' | 'negotiated' | NULL
    op.add_column(
        "contracts",
        sa.Column("mode", sa.String(16), nullable=True),
    )

    # Index on (source, created_at) for daemon polling
    op.create_index(
        "ix_contracts_source_created",
        "contracts",
        ["source", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_contracts_source_created", table_name="contracts")
    op.drop_column("contracts", "mode")
    op.drop_column("contracts", "draft_artifact_id")
    op.drop_column("contracts", "draft_request")
