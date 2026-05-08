"""Persistent dedup store for the Telegram bot (Sprint 4).

Two related concerns share one tiny SQLite database:

1. **Reminder dedup**: each `(approval_id, reminder_kind)` tuple is sent at
   most once for the lifetime of an approval. Survives bot restart.
2. **Pairing-code redemption**: each pairing code can be consumed exactly
   once. After redemption the code is rejected even if it has not yet
   expired. Survives bot restart.

Both stores live in a single sqlite3 file, default `~/.quill/bot-dedup.db`,
overridable via env var `QUILL_BOT_DEDUP_PATH`.

Why SQLite (not Redis): bot is single-process. We just need durability and
strict uniqueness. SQLite gives both with zero ops cost. If we ever scale
to multiple bot replicas the same schema lifts to Postgres — the SQL is
ANSI-portable.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger("quill.bot.dedup")


REMINDER_KINDS = (
    "lane2_4h",
    "lane2_8h",
    "lane3_12h",
    "critical_path_immediate",
    "safety_immediate",
)


def default_path() -> Path:
    p = os.environ.get("QUILL_BOT_DEDUP_PATH")
    if p:
        return Path(p).expanduser()
    return Path.home() / ".quill" / "bot-dedup.db"


class DedupStore:
    """Thread-safe wrapper around a tiny SQLite file.

    All public methods acquire `self._lock` so the store is safe to use
    from multiple asyncio tasks running on the same loop.
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS reminder_sent (
        approval_id   TEXT NOT NULL,
        reminder_kind TEXT NOT NULL,
        sent_at       TEXT NOT NULL,
        PRIMARY KEY (approval_id, reminder_kind)
    );
    CREATE TABLE IF NOT EXISTS pairing_redeemed (
        code         TEXT PRIMARY KEY,
        email        TEXT NOT NULL,
        chat_id      TEXT NOT NULL,
        redeemed_at  TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_reminder_sent_approval
        ON reminder_sent (approval_id);
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.path), check_same_thread=False, isolation_level=None
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(self.SCHEMA)

    # ------------------------------------------------------------------
    # Reminder dedup
    # ------------------------------------------------------------------
    def claim_reminder(self, approval_id: str, reminder_kind: str) -> bool:
        """Atomically claim `(approval_id, kind)` for sending. Returns True
        if this caller is the first to claim and should send the reminder.
        Subsequent calls for the same tuple return False.
        """
        if reminder_kind not in REMINDER_KINDS:
            log.warning("unknown reminder_kind=%r — accepting anyway", reminder_kind)
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO reminder_sent (approval_id, reminder_kind, sent_at)"
                    " VALUES (?, ?, ?)",
                    (approval_id, reminder_kind, datetime.now(UTC).isoformat()),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def reminder_sent(self, approval_id: str, reminder_kind: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM reminder_sent WHERE approval_id=? AND reminder_kind=?",
                (approval_id, reminder_kind),
            )
            return cur.fetchone() is not None

    def reset_approval(self, approval_id: str) -> int:
        """Drop all reminder rows for an approval (used when the approval
        terminates so we don't leak rows forever)."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM reminder_sent WHERE approval_id=?", (approval_id,)
            )
            return cur.rowcount or 0

    def reminder_count(self) -> int:
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM reminder_sent")
            row = cur.fetchone()
            return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # Pairing-code redemption
    # ------------------------------------------------------------------
    def claim_pairing(self, code: str, *, email: str, chat_id: str) -> bool:
        """Atomically mark `code` as redeemed. Returns True the first time,
        False if the code was already consumed.
        """
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO pairing_redeemed (code, email, chat_id, redeemed_at)"
                    " VALUES (?, ?, ?, ?)",
                    (code, email, chat_id, datetime.now(UTC).isoformat()),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def is_chat_paired(self, chat_id: str | int) -> bool:
        """True if any pairing has been redeemed for this chat_id."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM pairing_redeemed WHERE chat_id=? LIMIT 1",
                (str(chat_id),),
            )
            return cur.fetchone() is not None

    def get_paired_email(self, chat_id: str | int) -> str | None:
        """Return the most-recently redeemed email for a chat_id, or None."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT email FROM pairing_redeemed WHERE chat_id=? "
                "ORDER BY redeemed_at DESC LIMIT 1",
                (str(chat_id),),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def pairing_redeemed_at(self, code: str) -> datetime | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT redeemed_at FROM pairing_redeemed WHERE code=?", (code,)
            )
            row = cur.fetchone()
            if not row:
                return None
            try:
                return datetime.fromisoformat(row[0])
            except ValueError:
                return None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Process-wide singleton (matches the Notifier pattern)
# ---------------------------------------------------------------------------
_STORE: DedupStore | None = None
_STORE_LOCK = threading.Lock()


def get_store() -> DedupStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = DedupStore()
        return _STORE


def reset_store_for_tests(path: Path | str | None = None) -> DedupStore:
    """Tests call this to use an isolated DB file."""
    global _STORE
    with _STORE_LOCK:
        if _STORE is not None:
            _STORE.close()
        _STORE = DedupStore(path)
        return _STORE


__all__ = [
    "DedupStore",
    "REMINDER_KINDS",
    "default_path",
    "get_store",
    "reset_store_for_tests",
]
