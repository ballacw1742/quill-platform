"""Dev Chat tables — Sprint DC.1

Revision ID: 0009_dev_chat
Revises: 0008_document_metadata
Create Date: 2026-05-10

Creates three tables:
  - dev_chat_threads  — one per user, tracks idle/in_progress state
  - dev_chat_messages — conversation history (user + agent + system roles)
  - dev_chat_tasks    — task briefs written to ~/.openclaw/dev-chat-queue/

Index strategy:
  - dev_chat_messages: (thread_id, created_at) for paginated history load
  - dev_chat_tasks: (status) for the worker daemon's queued-poll query
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_dev_chat"
down_revision = "0008_document_metadata"
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

    # ------------------------------------------------------------------ #
    # dev_chat_threads
    # ------------------------------------------------------------------ #
    op.create_table(
        "dev_chat_threads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column(
            "state",
            sa.Enum("idle", "in_progress", name="dev_chat_thread_state"),
            nullable=False,
            server_default="idle",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ------------------------------------------------------------------ #
    # dev_chat_messages
    # ------------------------------------------------------------------ #
    op.create_table(
        "dev_chat_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("thread_id", sa.String(36), sa.ForeignKey("dev_chat_threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "role",
            sa.Enum("user", "agent", "system", name="dev_chat_message_role"),
            nullable=False,
        ),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("metadata", json_t, nullable=True),
        sa.Column(
            "status",
            sa.Enum("queued", "streaming", "completed", "failed", "cancelled", name="dev_chat_message_status"),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("commit_sha", sa.String(64), nullable=True),
        sa.Column("files_changed", json_t, nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_dev_chat_messages_thread_created",
        "dev_chat_messages",
        ["thread_id", "created_at"],
    )

    # ------------------------------------------------------------------ #
    # dev_chat_tasks
    # ------------------------------------------------------------------ #
    op.create_table(
        "dev_chat_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("message_id", sa.String(36), sa.ForeignKey("dev_chat_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("thread_id", sa.String(36), sa.ForeignKey("dev_chat_threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("branch", sa.String(256), nullable=False),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "completed", "failed", "cancelled", name="dev_chat_task_status"),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("budget_usd_cap", sa.Numeric(10, 6), nullable=False, server_default="2.0"),
        sa.Column("disallowed_paths", json_t, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
    )
    op.create_index(
        "ix_dev_chat_tasks_status",
        "dev_chat_tasks",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_dev_chat_tasks_status", table_name="dev_chat_tasks")
    op.drop_index("ix_dev_chat_messages_thread_created", table_name="dev_chat_messages")
    op.drop_table("dev_chat_tasks")
    op.drop_table("dev_chat_messages")
    op.drop_table("dev_chat_threads")

    # Drop enums for Postgres (SQLite doesn't use them)
    bind = op.get_bind()
    if _is_postgres(bind):
        op.execute("DROP TYPE IF EXISTS dev_chat_task_status")
        op.execute("DROP TYPE IF EXISTS dev_chat_message_status")
        op.execute("DROP TYPE IF EXISTS dev_chat_message_role")
        op.execute("DROP TYPE IF EXISTS dev_chat_thread_state")
