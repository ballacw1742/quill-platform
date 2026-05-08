"""Per-chat conversation history persistence (Phase B).

Stores Telegram-bot conversation turns (user / assistant / tool) in a small
SQLite database so the LLM has rolling context across messages within the
same chat. Storage is per-chat_id, default 24-message rolling window.

Tables:
    conversations(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        role TEXT NOT NULL,             -- 'user' | 'assistant' | 'tool'
        content TEXT,                   -- assistant/user text or tool result
        tool_calls TEXT,                -- JSON array (assistant turns w/ tool_use)
        tool_call_id TEXT,              -- for role=='tool' replies
        created_at TEXT NOT NULL        -- ISO-8601 UTC timestamp
    )
    INDEX ix_conv_chat_created (chat_id, created_at)

The store is intentionally tiny — we don't store anything that needs
long-term retention here; that lives in the audit log or Drive.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger("quill.bot.conversation")

Role = Literal["user", "assistant", "tool"]

DEFAULT_DB_PATH = Path(os.path.expanduser("~/.quill/bot-conversation.db"))
DEFAULT_KEEP = 24


@dataclass
class Message:
    """One message in a chat history."""

    chat_id: int
    role: Role
    content: str | None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    created_at: str = ""

    def to_anthropic(self) -> dict[str, Any]:
        """Convert to the Anthropic Messages-API shape.

        Anthropic uses two roles: 'user' and 'assistant'. Tool *results*
        are user-role messages with content blocks of type 'tool_result'.
        Tool *calls* are assistant-role messages with content blocks of
        type 'tool_use'.
        """
        if self.role == "user":
            return {"role": "user", "content": self.content or ""}

        if self.role == "assistant":
            blocks: list[dict[str, Any]] = []
            if self.content:
                blocks.append({"type": "text", "text": self.content})
            for tc in self.tool_calls or []:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc.get("input", {}),
                    }
                )
            if not blocks:
                # Anthropic rejects empty content; fall back to a space.
                blocks = [{"type": "text", "text": " "}]
            return {"role": "assistant", "content": blocks}

        # role == "tool" — Anthropic represents these as user-role
        # messages with a tool_result block.
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": self.tool_call_id or "",
                    "content": self.content or "",
                }
            ],
        }


class ConversationStore:
    """Thread-safe SQLite-backed conversation history.

    Single-process, single-bot use; the bot is not horizontally scaled.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            env_path = os.environ.get("QUILL_BOT_CONVERSATION_DB")
            db_path = Path(env_path) if env_path else DEFAULT_DB_PATH
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, isolation_level=None, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT,
                    tool_calls TEXT,
                    tool_call_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_conv_chat_created
                    ON conversations(chat_id, created_at);
                """
            )

    # ------------------------------------------------------------------
    def append(
        self,
        chat_id: int,
        role: Role,
        content: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
    ) -> None:
        """Append a single message to the chat's history."""
        ts = datetime.now(UTC).isoformat()
        tc_json = json.dumps(tool_calls) if tool_calls else None
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations (chat_id, role, content, tool_calls, tool_call_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (chat_id, role, content, tc_json, tool_call_id, ts),
            )

    def history(self, chat_id: int, max_messages: int = DEFAULT_KEEP) -> list[Message]:
        """Return the most recent `max_messages` messages, oldest first."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT chat_id, role, content, tool_calls, tool_call_id, created_at "
                "FROM conversations WHERE chat_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (chat_id, max_messages),
            ).fetchall()
        rows = list(reversed(rows))
        out: list[Message] = []
        for r in rows:
            tc_raw = r["tool_calls"]
            tc = json.loads(tc_raw) if tc_raw else None
            out.append(
                Message(
                    chat_id=r["chat_id"],
                    role=r["role"],
                    content=r["content"],
                    tool_calls=tc,
                    tool_call_id=r["tool_call_id"],
                    created_at=r["created_at"],
                )
            )
        return out

    def reset(self, chat_id: int) -> int:
        """Delete all history for one chat. Returns rows deleted."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM conversations WHERE chat_id = ?", (chat_id,)
            )
            return cur.rowcount

    def trim(self, chat_id: int, keep: int = DEFAULT_KEEP) -> int:
        """Keep only the most recent `keep` messages for the chat.

        Returns the number of rows deleted.
        """
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM conversations WHERE chat_id = ? "
                "ORDER BY id DESC LIMIT 1 OFFSET ?",
                (chat_id, keep),
            ).fetchone()
            if row is None:
                return 0
            cutoff_id = row["id"]
            cur = conn.execute(
                "DELETE FROM conversations WHERE chat_id = ? AND id <= ?",
                (chat_id, cutoff_id),
            )
            return cur.rowcount

    def count(self, chat_id: int) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM conversations WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            return int(row["n"])


# Singleton helper for the bot process ---------------------------------
_store: ConversationStore | None = None


def get_store() -> ConversationStore:
    global _store
    if _store is None:
        _store = ConversationStore()
    return _store


def reset_store_for_tests(db_path: Path | str | None = None) -> ConversationStore:
    """Test helper: rebind the module-global store to a fresh DB."""
    global _store
    _store = ConversationStore(db_path)
    return _store


__all__ = [
    "ConversationStore",
    "Message",
    "Role",
    "get_store",
    "reset_store_for_tests",
    "DEFAULT_KEEP",
]
