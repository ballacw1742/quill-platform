"""documents table \u2014 Phase D.1

Revision ID: 0005_documents
Revises: 0004_audit_mirror_claims
Create Date: 2026-05-08

Creates the `documents` table backing the Documents workspace
(api.routes.documents). On Postgres adds a generated tsvector column +
GIN index over title (A) / summary (B) / body_markdown (C). On SQLite
(dev) the tsvector column is omitted and search falls back to LIKE.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_documents"
down_revision = "0004_audit_mirror_claims"
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

    cols = [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("artifact_id", sa.String(36), nullable=False, unique=True),
        sa.Column("artifact_type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("summary", sa.String(512), nullable=False, server_default=""),
        sa.Column("body_markdown", sa.Text, nullable=False, server_default=""),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("agent_display_name", sa.String(128), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(128), nullable=True),
        sa.Column(
            "approval_id",
            sa.String(36),
            sa.ForeignKey("approval_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tags", json_t, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("drive_url", sa.String(512), nullable=True),
        sa.Column("minio_path", sa.String(512), nullable=True),
    ]

    op.create_table("documents", *cols)

    op.create_index("ix_documents_artifact_id", "documents", ["artifact_id"], unique=True)
    op.create_index("ix_documents_artifact_type", "documents", ["artifact_type"])
    op.create_index("ix_documents_agent_id", "documents", ["agent_id"])
    op.create_index("ix_documents_created_at", "documents", ["created_at"])
    op.create_index(
        "ix_documents_artifact_type_created",
        "documents",
        ["artifact_type", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_documents_agent_created",
        "documents",
        ["agent_id", sa.text("created_at DESC")],
    )

    if _is_postgres(bind):
        # Generated tsvector column. Postgres 12+ supports `GENERATED ALWAYS AS ... STORED`.
        op.execute(
            """
            ALTER TABLE documents
            ADD COLUMN search_vector tsvector
            GENERATED ALWAYS AS (
              setweight(to_tsvector('english', coalesce(title,'')), 'A') ||
              setweight(to_tsvector('english', coalesce(summary,'')), 'B') ||
              setweight(to_tsvector('english', coalesce(body_markdown,'')), 'C')
            ) STORED
            """
        )
        op.execute(
            "CREATE INDEX ix_documents_search_vector ON documents USING GIN (search_vector)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _is_postgres(bind):
        op.execute("DROP INDEX IF EXISTS ix_documents_search_vector")
        # column drops with the table

    op.drop_index("ix_documents_agent_created", table_name="documents")
    op.drop_index("ix_documents_artifact_type_created", table_name="documents")
    op.drop_index("ix_documents_created_at", table_name="documents")
    op.drop_index("ix_documents_agent_id", table_name="documents")
    op.drop_index("ix_documents_artifact_type", table_name="documents")
    op.drop_index("ix_documents_artifact_id", table_name="documents")
    op.drop_table("documents")
