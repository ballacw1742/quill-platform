"""Add metadata JSON column to documents table — Sprint G.7

Revision ID: 0008_document_metadata
Revises: 0007_cost_library
Create Date: 2026-05-10

Adds a nullable JSON/JSONB column named ``metadata`` to the ``documents``
table. This stores the full artifact payload dict so the frontend can
render rich views (cost tables, schedule timelines) without a second API
call. Existing rows are left as NULL; new approvals populate it via
DocumentsService.create_from_approval.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_document_metadata"
down_revision = "0007_cost_library"
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

    op.add_column(
        "documents",
        sa.Column("metadata", json_t, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "metadata")
