"""Project requests table — Requests tab sprint

Revision ID: 0013_project_requests
Revises: 0012_contract_drafts
Create Date: 2026-06-27

Creates the ``project_requests`` table that backs the Requests chat tab.

Columns:
  - id            (VARCHAR 36, PK)
  - user_id       (VARCHAR 36, FK → users.id, indexed)
  - message       (TEXT) — the user's raw request text
  - intent        (VARCHAR 50) — classify: estimate|schedule|rfi|contract|general
  - status        (VARCHAR 20) — processing|complete|failed
  - response      (TEXT, nullable) — agent response text
  - output_module (VARCHAR 50, nullable) — which module owns the output
  - output_id     (VARCHAR 36, nullable) — ID in that module
  - drive_url     (VARCHAR 500, nullable) — Google Drive link if provided
  - filenames     (TEXT, nullable) — comma-separated original filenames
  - created_at    (TIMESTAMP WITH TZ)
  - updated_at    (TIMESTAMP WITH TZ)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_project_requests"
down_revision = "0012_contract_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("intent", sa.String(50), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="processing", index=True),
        sa.Column("response", sa.Text, nullable=True),
        sa.Column("output_module", sa.String(50), nullable=True),
        sa.Column("output_id", sa.String(36), nullable=True),
        sa.Column("drive_url", sa.String(500), nullable=True),
        sa.Column("filenames", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_project_requests_user_created",
        "project_requests",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_project_requests_user_created", table_name="project_requests")
    op.drop_table("project_requests")
