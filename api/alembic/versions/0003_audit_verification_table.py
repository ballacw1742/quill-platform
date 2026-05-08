"""audit chain verification table — Sprint 2.3

Revision ID: 0003_audit_verify
Revises: 0002_webauthn_fields
Create Date: 2026-05-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_audit_verify"
down_revision = "0002_webauthn_fields"
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
        "audit_chain_verifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("scope", sa.String(32), nullable=False, server_default="global"),
        sa.Column("scope_ref", sa.String(128), nullable=True),
        sa.Column("result", sa.String(32), nullable=False, server_default="running"),
        sa.Column("chain_length_postgres", sa.Integer, nullable=True),
        sa.Column("chain_length_mirror", sa.Integer, nullable=True),
        sa.Column("last_hash_postgres", sa.String(64), nullable=True),
        sa.Column("last_hash_mirror", sa.String(64), nullable=True),
        sa.Column("details", json_t, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("triggered_by", sa.String(64), nullable=False, server_default="cron"),
    )
    op.create_index(
        "ix_audit_chain_verifications_started_at",
        "audit_chain_verifications",
        ["started_at"],
    )
    op.create_index(
        "ix_audit_verifications_started",
        "audit_chain_verifications",
        ["started_at"],
    )
    op.create_index(
        "ix_audit_chain_verifications_scope",
        "audit_chain_verifications",
        ["scope"],
    )
    op.create_index(
        "ix_audit_chain_verifications_result",
        "audit_chain_verifications",
        ["result"],
    )
    op.create_index(
        "ix_audit_verifications_result",
        "audit_chain_verifications",
        ["result"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_verifications_result", table_name="audit_chain_verifications")
    op.drop_index("ix_audit_chain_verifications_result", table_name="audit_chain_verifications")
    op.drop_index("ix_audit_chain_verifications_scope", table_name="audit_chain_verifications")
    op.drop_index("ix_audit_verifications_started", table_name="audit_chain_verifications")
    op.drop_index("ix_audit_chain_verifications_started_at", table_name="audit_chain_verifications")
    op.drop_table("audit_chain_verifications")
