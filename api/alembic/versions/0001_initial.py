"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
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
    if _is_postgres(bind):
        op.execute("CREATE EXTENSION IF NOT EXISTS pgvector")  # tolerated even if absent
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    json_t = _json_type(bind)

    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="observer"),
        sa.Column("password_hash", sa.String(256)),
        sa.Column("telegram_chat_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "webauthn_credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("credential_id_b64", sa.String(512), nullable=False),
        sa.Column("public_key_b64", sa.Text, nullable=False),
        sa.Column("sign_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("name", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("credential_id_b64", name="uq_webauthn_credential_id"),
    )
    op.create_index("ix_webauthn_credentials_user_id", "webauthn_credentials", ["user_id"])

    op.create_table(
        "agent_registrations",
        sa.Column("agent_id", sa.String(64), primary_key=True),
        sa.Column("version", sa.String(32), nullable=False, server_default="0.0.0"),
        sa.Column("trust_tier", sa.String(32), nullable=False, server_default="tier-0-mandatory"),
        sa.Column("default_lane", sa.Integer, nullable=False, server_default="2"),
        sa.Column("monthly_token_budget", sa.Integer, nullable=False, server_default="1000000"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "approval_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("agent_version", sa.String(32), nullable=False, server_default="0.0.0"),
        sa.Column("workflow", sa.String(128), nullable=False),
        sa.Column("lane", sa.Integer, nullable=False, server_default="2"),
        sa.Column("priority", sa.String(32), nullable=False, server_default="normal"),
        sa.Column("target_system", sa.String(32), nullable=False, server_default="none"),
        sa.Column("api_call", sa.String(256)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sla_due_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.Column("payload", json_t, nullable=False),
        sa.Column("source_artifacts", json_t, nullable=False),
        sa.Column("citations", json_t, nullable=False),
        sa.Column("agent_confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("agent_reasoning", sa.Text),
        sa.Column("agent_model", sa.String(128)),
        sa.Column("agent_prompt_version", sa.String(64)),
        sa.Column("agent_input_hash", sa.String(64)),
        sa.Column("agent_output_hash", sa.String(64)),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("required_approvers", json_t, nullable=False),
        sa.Column("execution_result", sa.String(32)),
        sa.Column("external_ref", sa.String(256)),
        sa.Column("audit_hash", sa.String(64)),
        sa.Column("prev_audit_hash", sa.String(64)),
        sa.Column("litigation_hold", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("suspended_reason", sa.Text),
    )
    op.create_index("ix_approval_items_agent_id", "approval_items", ["agent_id"])
    op.create_index("ix_approval_items_workflow", "approval_items", ["workflow"])
    op.create_index("ix_approval_items_lane", "approval_items", ["lane"])
    op.create_index("ix_approval_items_priority", "approval_items", ["priority"])
    op.create_index("ix_approval_items_created_at", "approval_items", ["created_at"])
    op.create_index("ix_approval_items_sla_due_at", "approval_items", ["sla_due_at"])
    op.create_index("ix_approval_items_status", "approval_items", ["status"])
    op.create_index("ix_approval_items_status_lane", "approval_items", ["status", "lane"])
    op.create_index("ix_approval_items_status_sla", "approval_items", ["status", "sla_due_at"])
    op.create_index("ix_approval_items_agent_status", "approval_items", ["agent_id", "status"])

    op.create_table(
        "approval_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "approval_item_id",
            sa.String(36),
            sa.ForeignKey("approval_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("approver_id", sa.String(36), nullable=False),
        sa.Column("approver_role", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("edits", json_t),
        sa.Column("rejection_reason", sa.Text),
        sa.Column("auth_method", sa.String(32), nullable=False, server_default="dev_token"),
        sa.Column("auth_evidence", sa.Text),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_approval_records_approval_item_id", "approval_records", ["approval_item_id"])
    op.create_index("ix_approval_records_approver_id", "approval_records", ["approver_id"])
    op.create_index("ix_approval_records_timestamp", "approval_records", ["timestamp"])

    op.create_table(
        "audit_log_entries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("approval_item_id", sa.String(36)),
        sa.Column("payload", json_t, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.Column("prev_hash", sa.String(64)),
    )
    op.create_index("ix_audit_log_entries_event_type", "audit_log_entries", ["event_type"])
    op.create_index("ix_audit_log_entries_actor", "audit_log_entries", ["actor"])
    op.create_index("ix_audit_log_entries_approval_item_id", "audit_log_entries", ["approval_item_id"])
    op.create_index("ix_audit_log_entries_timestamp", "audit_log_entries", ["timestamp"])
    op.create_index("ix_audit_log_entries_hash", "audit_log_entries", ["hash"])
    op.create_index("ix_audit_chain", "audit_log_entries", ["approval_item_id", "id"])


def downgrade() -> None:
    op.drop_table("audit_log_entries")
    op.drop_table("approval_records")
    op.drop_table("approval_items")
    op.drop_table("agent_registrations")
    op.drop_table("webauthn_credentials")
    op.drop_table("users")
