"""estimates table — Phase G.1

Revision ID: 0006_estimates
Revises: 0005_documents
Create Date: 2026-05-09

Tracks drawing-upload runs from POST /v1/estimates/upload through
extraction → classification → estimating. Works on both Postgres and
SQLite.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_estimates"
down_revision = "0005_documents"
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
        "estimates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("upload_id", sa.String(36), nullable=False, unique=True),
        sa.Column("project_label", sa.String(200), nullable=False, server_default=""),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("uploaded_files", json_t, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("classification_artifact_id", sa.String(64), nullable=True),
        sa.Column("package_artifact_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("error_message", sa.Text, nullable=True),
    )

    op.create_index("ix_estimates_upload_id", "estimates", ["upload_id"], unique=True)
    op.create_index("ix_estimates_status", "estimates", ["status"])
    op.create_index("ix_estimates_created_at", "estimates", ["created_at"])
    op.create_index(
        "ix_estimates_status_created", "estimates", ["status", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_estimates_status_created", table_name="estimates")
    op.drop_index("ix_estimates_created_at", table_name="estimates")
    op.drop_index("ix_estimates_status", table_name="estimates")
    op.drop_index("ix_estimates_upload_id", table_name="estimates")
    op.drop_table("estimates")
