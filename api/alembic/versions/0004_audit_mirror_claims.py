"""audit-mirror replica claim table — Sprint 4 fix #8

Revision ID: 0004_audit_mirror_claims
Revises: 0003_audit_verify
Create Date: 2026-05-08

Multi-replica deploys would each enqueue + write the same audit-log entry to
B2. The object key already embeds the chain hash so the result is safe, but
we still pay the B2 PUT charges N times. With this table, only the replica
that wins the `INSERT ... ON CONFLICT DO NOTHING RETURNING hash` race actually
writes.

We keep `claimed_at` so a periodic janitor can drop rows older than the
B2 retention window (or the bucket lifecycle, whichever comes first).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_audit_mirror_claims"
down_revision = "0003_audit_verify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_mirror_claims",
        sa.Column("hash", sa.String(64), primary_key=True),
        sa.Column(
            "claimed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("replica_id", sa.String(128), nullable=False, server_default="unknown"),
        sa.Column("seq", sa.Integer, nullable=True),
    )
    op.create_index(
        "ix_audit_mirror_claims_claimed_at",
        "audit_mirror_claims",
        ["claimed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_audit_mirror_claims_claimed_at", table_name="audit_mirror_claims"
    )
    op.drop_table("audit_mirror_claims")
