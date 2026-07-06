"""Campus monitoring agents — Sprint 5.4 (Campus Template Automation)

Revision ID: 0024_campus_monitoring_agents
Revises: 0023_account_campus_link
Create Date: 2026-07-06

Changes:
  - New table campus_monitoring_agents: monitoring agents registered for a
    campus by the deploy-from-template workflow.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_campus_monitoring_agents"
down_revision = "0023_account_campus_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campus_monitoring_agents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "campus_id",
            sa.String(36),
            sa.ForeignKey("campuses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_key", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("agent_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="registered"),
        sa.Column("endpoint_url", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_campus_monitoring_agents_campus_id", "campus_monitoring_agents", ["campus_id"])
    op.create_index("ix_campus_monitoring_agents_agent_key", "campus_monitoring_agents", ["agent_key"])
    op.create_index("ix_campus_monitoring_agents_status", "campus_monitoring_agents", ["status"])
    op.create_index("ix_campus_monitoring_agents_created_at", "campus_monitoring_agents", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_campus_monitoring_agents_created_at", table_name="campus_monitoring_agents")
    op.drop_index("ix_campus_monitoring_agents_status", table_name="campus_monitoring_agents")
    op.drop_index("ix_campus_monitoring_agents_agent_key", table_name="campus_monitoring_agents")
    op.drop_index("ix_campus_monitoring_agents_campus_id", table_name="campus_monitoring_agents")
    op.drop_table("campus_monitoring_agents")
