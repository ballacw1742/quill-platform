"""webauthn credential fields — Sprint 2.2

Revision ID: 0002_webauthn_fields
Revises: 0001_initial
Create Date: 2026-05-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_webauthn_fields"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("webauthn_credentials") as batch:
        batch.add_column(sa.Column("transports", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("attachment", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("aaguid", sa.String(length=64), nullable=True))
        batch.add_column(
            sa.Column(
                "backup_eligible", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch.add_column(
            sa.Column(
                "backup_state", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch.add_column(sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("webauthn_credentials") as batch:
        for col in (
            "revoked_at",
            "last_used_at",
            "backup_state",
            "backup_eligible",
            "aaguid",
            "attachment",
            "transports",
        ):
            batch.drop_column(col)
