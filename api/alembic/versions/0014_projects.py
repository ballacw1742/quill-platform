"""Projects table — Sprint DC.2 DataSite + Projects integration

Revision ID: 0014_projects
Revises: 0013_project_requests
Create Date: 2026-07-01

Creates the ``projects`` table that backs the Projects module.
Projects can be created from a DataSite site evaluation or standalone.

Columns:
  - id            (VARCHAR 36, PK)
  - user_id       (VARCHAR 36, indexed)
  - name          (VARCHAR 255)
  - address       (VARCHAR 500, nullable)
  - site_id       (VARCHAR 36, nullable) — DataSite site_id if created from site
  - site_score    (FLOAT, nullable) — site total weighted score at time of creation
  - site_verdict  (VARCHAR 50, nullable) — strong_recommend | conditional | etc.
  - workload_type (VARCHAR 100, nullable)
  - phase         (VARCHAR 50) — site_control|permitting|design|construction|commissioning|turnover
  - status        (VARCHAR 30) — active|on_hold|complete|cancelled
  - notes         (TEXT, nullable)
  - created_at    (TIMESTAMP WITH TZ)
  - updated_at    (TIMESTAMP WITH TZ)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_projects"
down_revision = "0013_project_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("site_id", sa.String(36), nullable=True, index=True),
        sa.Column("site_score", sa.Float, nullable=True),
        sa.Column("site_verdict", sa.String(50), nullable=True),
        sa.Column("workload_type", sa.String(100), nullable=True),
        sa.Column("phase", sa.String(50), nullable=False, server_default="site_control", index=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="active", index=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_projects_user_created",
        "projects",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_projects_user_created", table_name="projects")
    op.drop_table("projects")
