"""Agent Registry expansion — Sprint DC.4

Revision ID: 0015_agent_registry_expand
Revises: 0014_projects
Create Date: 2026-07-01

Adds new columns to ``agent_registrations`` for the Agent Registry feature:
  - display_name      (VARCHAR 128) — human-readable name
  - description       (TEXT, nullable) — full agent description
  - role_summary      (TEXT, nullable) — short role label (e.g. "Orchestrator")
  - handled_intents   (TEXT, nullable) — JSON array of intent strings
  - framework         (VARCHAR 32) — adk | datasite | internal
  - endpoint_url      (VARCHAR 500, nullable) — Cloud Run URL
  - requests_total    (INTEGER) — lifetime dispatch count
  - requests_success  (INTEGER) — successful dispatches
  - requests_failed   (INTEGER) — failed dispatches
  - last_invoked_at   (TIMESTAMP WITH TZ, nullable) — last dispatch time
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_agent_registry_expand"
down_revision = "0014_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_registrations") as batch_op:
        batch_op.add_column(sa.Column("display_name", sa.String(128), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("role_summary", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("handled_intents", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("framework", sa.String(32), nullable=False, server_default="adk"))
        batch_op.add_column(sa.Column("endpoint_url", sa.String(500), nullable=True))
        batch_op.add_column(sa.Column("requests_total", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("requests_success", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("requests_failed", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("last_invoked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_registrations") as batch_op:
        batch_op.drop_column("last_invoked_at")
        batch_op.drop_column("requests_failed")
        batch_op.drop_column("requests_success")
        batch_op.drop_column("requests_total")
        batch_op.drop_column("endpoint_url")
        batch_op.drop_column("framework")
        batch_op.drop_column("handled_intents")
        batch_op.drop_column("role_summary")
        batch_op.drop_column("description")
        batch_op.drop_column("display_name")
