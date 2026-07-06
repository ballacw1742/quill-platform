"""Dispatcher state stores — Sprint 5.5 (GCP worker).

The four dispatch daemons historically persisted their "already dispatched"
markers in local JSON files under ``runtime/_state/``. That works for a
single daemon on a single machine, but not for a Cloud Run worker where the
filesystem is ephemeral and multiple replicas may race.

This module introduces a small state-store abstraction:

- :class:`FileStateStore` — wraps the legacy JSON-file behavior 1:1
  (single-process semantics, atomic tmp→rename writes). Used by default so
  local dev / tests / the Mac daemons keep working unchanged.
- :class:`PostgresStateStore` — a Postgres-backed store with **atomic claim
  semantics** so that N worker replicas never double-process the same
  item. Enabled by setting ``RUNTIME_STATE_DATABASE_URL``.

Claim model (Postgres):

- ``try_claim(item_id)`` atomically inserts / takes over a row in
  ``runtime_dispatch_state`` with ``status='claimed'`` and a lease. Only one
  concurrent caller wins. A claim may be (re)taken when:
    * no row exists yet, or
    * the row is ``status='error'`` and its ``retry_after`` has passed, or
    * the row is ``status='claimed'`` but its lease expired (crashed worker).
- ``record_success(item_id, approval_item_id)`` → ``status='done'`` (terminal).
- ``record_error(item_id, error)`` → ``status='error'`` with exponential
  backoff in ``retry_after`` (30s * 2^(attempt-1), capped at 5 minutes —
  same policy the file-based dispatchers used).
- ``release_claim(item_id)`` deletes a non-terminal claim so the item is
  immediately retryable (used when a guard says "not ready yet" rather than
  "failed").

The table is created on first use (``CREATE TABLE IF NOT EXISTS``); it is
intentionally owned by the runtime, not by the API's Alembic migrations, so
the worker has no coupling to API deploys.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import structlog

log = structlog.get_logger(__name__)

# Backoff policy — mirrors the historical per-dispatcher constants.
_MAX_BACKOFF_S = 5 * 60
_INITIAL_BACKOFF_S = 30.0

# Default lease for an in-flight Postgres claim. The estimator (heaviest
# agent, extended thinking) can take several minutes; 15 minutes is a safe
# upper bound before a crashed worker's claim becomes stealable.
_DEFAULT_LEASE_SECONDS = 15 * 60

_ENV_DSN = "RUNTIME_STATE_DATABASE_URL"

_DDL = """
CREATE TABLE IF NOT EXISTS runtime_dispatch_state (
    dispatcher        TEXT        NOT NULL,
    item_id           TEXT        NOT NULL,
    status            TEXT        NOT NULL,
    attempt           INTEGER     NOT NULL DEFAULT 0,
    approval_item_id  TEXT,
    error             TEXT,
    claimed_at        TIMESTAMPTZ,
    lease_expires_at  TIMESTAMPTZ,
    retry_after       TIMESTAMPTZ,
    dispatched_at     TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (dispatcher, item_id)
);
"""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _backoff_for(attempt: int) -> float:
    return min(_INITIAL_BACKOFF_S * (2 ** (attempt - 1)), _MAX_BACKOFF_S)


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------
class DispatchStateStore(ABC):
    """Persistence + claim semantics for a single dispatcher's work items."""

    dispatcher: str

    async def setup(self) -> None:  # pragma: no cover - trivial default
        """Prepare the backing store (create tables / dirs). Idempotent."""

    async def aclose(self) -> None:  # pragma: no cover - trivial default
        """Release connections."""

    @abstractmethod
    async def is_done(self, item_id: str) -> bool:
        """True if ``item_id`` has already been successfully processed."""

    @abstractmethod
    async def try_claim(self, item_id: str) -> bool:
        """Atomically claim ``item_id`` for processing.

        Returns True if the caller now owns processing of the item.
        Returns False if the item is done, claimed elsewhere, or in
        error-backoff.
        """

    @abstractmethod
    async def release_claim(self, item_id: str) -> None:
        """Give up a claim without recording success/error (item not ready)."""

    @abstractmethod
    async def record_success(
        self, item_id: str, approval_item_id: str | None
    ) -> None:
        """Mark ``item_id`` as processed (terminal)."""

    @abstractmethod
    async def record_error(self, item_id: str, error: str) -> None:
        """Mark ``item_id`` as failed; sets retry backoff."""

    @abstractmethod
    async def status_summary(self) -> dict[str, Any]:
        """JSON-serializable summary (dispatched/error counts + recents)."""


# ---------------------------------------------------------------------------
# File-backed store (legacy semantics, single process)
# ---------------------------------------------------------------------------
@dataclass
class _FileDispatched:
    dispatched_at: str
    approval_item_id: str | None = None


@dataclass
class _FileError:
    item_id: str
    error: str
    failed_at: str
    retry_after: str
    attempt: int = 1


@dataclass
class _FileState:
    dispatched: dict[str, _FileDispatched] = field(default_factory=dict)
    errors: list[_FileError] = field(default_factory=list)


class FileStateStore(DispatchStateStore):
    """JSON-file store with the exact legacy schema.

    File schema (unchanged from the Sprint 4 daemons)::

        {
          "dispatched": {"<id>": {"dispatched_at": "...", "approval_item_id": "..."}},
          "errors": [{"upload_id": "...", "error": "...", "failed_at": "...",
                      "retry_after": "...", "attempt": 1}]
        }

    Single-process semantics: ``try_claim`` does not persist a marker — it
    only checks done/backoff state, exactly like the old ``_is_dispatched``
    + retry-backoff checks. This is safe because the file store is only used
    when one dispatcher process owns the file (launchd / dev).
    """

    def __init__(self, dispatcher: str, state_file: Path) -> None:
        self.dispatcher = dispatcher
        self.state_file = Path(state_file)
        self._state = self._load()

    # -- persistence ------------------------------------------------------
    def _load(self) -> _FileState:
        if not self.state_file.exists():
            return _FileState()
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
            dispatched = {
                str(uid): _FileDispatched(
                    dispatched_at=v.get("dispatched_at", ""),
                    approval_item_id=v.get("approval_item_id"),
                )
                for uid, v in (raw.get("dispatched") or {}).items()
            }
            errors = [
                _FileError(
                    item_id=e["upload_id"],
                    error=e.get("error", ""),
                    failed_at=e.get("failed_at", ""),
                    retry_after=e.get("retry_after", ""),
                    attempt=int(e.get("attempt", 1)),
                )
                for e in (raw.get("errors") or [])
            ]
            return _FileState(dispatched=dispatched, errors=errors)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "state_store.file_load_failed",
                dispatcher=self.dispatcher,
                err=str(exc),
            )
            return _FileState()

    def _save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "dispatched": {
                uid: {
                    "dispatched_at": e.dispatched_at,
                    "approval_item_id": e.approval_item_id,
                }
                for uid, e in self._state.dispatched.items()
            },
            "errors": [
                {
                    "upload_id": e.item_id,
                    "error": e.error,
                    "failed_at": e.failed_at,
                    "retry_after": e.retry_after,
                    "attempt": e.attempt,
                }
                for e in self._state.errors
            ],
        }
        tmp = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self.state_file)

    # -- helpers -----------------------------------------------------------
    def _error_entry(self, item_id: str) -> _FileError | None:
        for e in self._state.errors:
            if e.item_id == item_id:
                return e
        return None

    @staticmethod
    def _retryable(entry: _FileError) -> bool:
        try:
            return _utcnow() >= datetime.fromisoformat(entry.retry_after)
        except Exception:  # noqa: BLE001
            return True

    # -- interface ----------------------------------------------------------
    async def is_done(self, item_id: str) -> bool:
        return item_id in self._state.dispatched

    async def try_claim(self, item_id: str) -> bool:
        if item_id in self._state.dispatched:
            return False
        entry = self._error_entry(item_id)
        if entry and not self._retryable(entry):
            return False
        return True

    async def release_claim(self, item_id: str) -> None:
        return None  # nothing persisted at claim time

    async def record_success(
        self, item_id: str, approval_item_id: str | None
    ) -> None:
        self._state.errors = [
            e for e in self._state.errors if e.item_id != item_id
        ]
        self._state.dispatched[item_id] = _FileDispatched(
            dispatched_at=_utcnow().isoformat(),
            approval_item_id=approval_item_id,
        )
        self._save()

    async def record_error(self, item_id: str, error: str) -> None:
        existing = self._error_entry(item_id)
        attempt = (existing.attempt + 1) if existing else 1
        retry_after = (
            _utcnow() + timedelta(seconds=_backoff_for(attempt))
        ).isoformat()
        self._state.errors = [
            e for e in self._state.errors if e.item_id != item_id
        ]
        self._state.errors.append(
            _FileError(
                item_id=item_id,
                error=error,
                failed_at=_utcnow().isoformat(),
                retry_after=retry_after,
                attempt=attempt,
            )
        )
        self._save()

    async def status_summary(self) -> dict[str, Any]:
        self._state = self._load()
        dispatched = sorted(
            self._state.dispatched.items(),
            key=lambda kv: kv[1].dispatched_at,
            reverse=True,
        )
        return {
            "backend": "file",
            "dispatched_count": len(dispatched),
            "error_count": len(self._state.errors),
            "recent_dispatched": [
                {
                    "upload_id": uid,
                    "dispatched_at": e.dispatched_at,
                    "approval_item_id": e.approval_item_id,
                }
                for uid, e in dispatched[:10]
            ],
            "recent_errors": [
                {
                    "upload_id": e.item_id,
                    "error": e.error,
                    "failed_at": e.failed_at,
                    "retry_after": e.retry_after,
                    "attempt": e.attempt,
                }
                for e in self._state.errors[-10:]
            ],
        }


# ---------------------------------------------------------------------------
# Postgres-backed store (multi-replica safe)
# ---------------------------------------------------------------------------
def _parse_pg_dsn(dsn: str) -> dict[str, Any]:
    """Parse a SQLAlchemy-style or plain Postgres URL into asyncpg kwargs.

    Handles the Cloud SQL unix-socket convention used by the API::

        postgresql+asyncpg://user:pw@/dbname?host=/cloudsql/PROJECT:REGION:INSTANCE
    """
    normalized = dsn.strip()
    if normalized.startswith("postgresql+asyncpg://"):
        normalized = "postgresql://" + normalized[len("postgresql+asyncpg://") :]
    elif normalized.startswith("postgres+asyncpg://"):
        normalized = "postgresql://" + normalized[len("postgres+asyncpg://") :]

    parsed = urlparse(normalized)
    query = parse_qs(parsed.query)
    kwargs: dict[str, Any] = {}
    if parsed.username:
        kwargs["user"] = unquote(parsed.username)
    if parsed.password:
        kwargs["password"] = unquote(parsed.password)
    db = (parsed.path or "").lstrip("/")
    if db:
        kwargs["database"] = unquote(db)
    host = query.get("host", [None])[0] or parsed.hostname
    if host:
        kwargs["host"] = unquote(host) if "%" in host else host
    if parsed.port:
        kwargs["port"] = parsed.port
    return kwargs


# One pool per DSN, shared across the four dispatcher stores in a worker
# process. Keeps total Postgres connections bounded (db-f1-micro has a low
# max_connections and the API needs most of them).
_POOL_CACHE: dict[str, Any] = {}
_POOL_LOCKS: dict[str, Any] = {}


class PostgresStateStore(DispatchStateStore):
    """asyncpg-backed store with atomic claim/lease semantics."""

    def __init__(
        self,
        dispatcher: str,
        dsn: str,
        *,
        lease_seconds: int = _DEFAULT_LEASE_SECONDS,
    ) -> None:
        self.dispatcher = dispatcher
        self._dsn = dsn
        self._lease_seconds = lease_seconds

    async def _ensure_pool(self) -> Any:
        import asyncio

        pool = _POOL_CACHE.get(self._dsn)
        if pool is not None:
            return pool
        lock = _POOL_LOCKS.setdefault(self._dsn, asyncio.Lock())
        async with lock:
            pool = _POOL_CACHE.get(self._dsn)
            if pool is None:
                import asyncpg  # imported lazily; not a hard dep for file mode

                pool = await asyncpg.create_pool(
                    min_size=0, max_size=4, **_parse_pg_dsn(self._dsn)
                )
                async with pool.acquire() as conn:
                    await conn.execute(_DDL)
                _POOL_CACHE[self._dsn] = pool
                log.info(
                    "state_store.pg_ready",
                    dispatcher=self.dispatcher,
                    table="runtime_dispatch_state",
                )
        return pool

    async def setup(self) -> None:
        await self._ensure_pool()

    async def aclose(self) -> None:
        pool = _POOL_CACHE.pop(self._dsn, None)
        _POOL_LOCKS.pop(self._dsn, None)
        if pool is not None:
            await pool.close()

    async def is_done(self, item_id: str) -> bool:
        pool = await self._ensure_pool()
        row = await pool.fetchrow(
            """
            SELECT 1 FROM runtime_dispatch_state
            WHERE dispatcher = $1 AND item_id = $2 AND status = 'done'
            """,
            self.dispatcher,
            item_id,
        )
        return row is not None

    async def try_claim(self, item_id: str) -> bool:
        pool = await self._ensure_pool()
        lease = timedelta(seconds=self._lease_seconds)
        row = await pool.fetchrow(
            """
            INSERT INTO runtime_dispatch_state
                (dispatcher, item_id, status, attempt, claimed_at,
                 lease_expires_at, updated_at)
            VALUES ($1, $2, 'claimed', 0, now(), now() + $3, now())
            ON CONFLICT (dispatcher, item_id) DO UPDATE
            SET status = 'claimed',
                claimed_at = now(),
                lease_expires_at = now() + $3,
                updated_at = now()
            WHERE (runtime_dispatch_state.status = 'error'
                   AND runtime_dispatch_state.retry_after <= now())
               OR (runtime_dispatch_state.status = 'claimed'
                   AND runtime_dispatch_state.lease_expires_at <= now())
            RETURNING item_id
            """,
            self.dispatcher,
            item_id,
            lease,
        )
        return row is not None

    async def release_claim(self, item_id: str) -> None:
        pool = await self._ensure_pool()
        await pool.execute(
            """
            DELETE FROM runtime_dispatch_state
            WHERE dispatcher = $1 AND item_id = $2 AND status = 'claimed'
            """,
            self.dispatcher,
            item_id,
        )

    async def record_success(
        self, item_id: str, approval_item_id: str | None
    ) -> None:
        pool = await self._ensure_pool()
        await pool.execute(
            """
            INSERT INTO runtime_dispatch_state
                (dispatcher, item_id, status, approval_item_id,
                 dispatched_at, updated_at)
            VALUES ($1, $2, 'done', $3, now(), now())
            ON CONFLICT (dispatcher, item_id) DO UPDATE
            SET status = 'done',
                approval_item_id = EXCLUDED.approval_item_id,
                error = NULL,
                retry_after = NULL,
                dispatched_at = now(),
                updated_at = now()
            """,
            self.dispatcher,
            item_id,
            approval_item_id,
        )

    async def record_error(self, item_id: str, error: str) -> None:
        pool = await self._ensure_pool()
        # attempt increments on each recorded failure; backoff derives from it.
        await pool.execute(
            """
            INSERT INTO runtime_dispatch_state
                (dispatcher, item_id, status, attempt, error,
                 retry_after, updated_at)
            VALUES ($1, $2, 'error', 1, $3,
                    now() + make_interval(secs => $4), now())
            ON CONFLICT (dispatcher, item_id) DO UPDATE
            SET status = 'error',
                attempt = runtime_dispatch_state.attempt + 1,
                error = EXCLUDED.error,
                retry_after = now() + make_interval(
                    secs => LEAST(
                        $5 * power(2, runtime_dispatch_state.attempt),
                        $6
                    )
                ),
                updated_at = now()
            """,
            self.dispatcher,
            item_id,
            error[:2000],
            _backoff_for(1),
            _INITIAL_BACKOFF_S,
            float(_MAX_BACKOFF_S),
        )

    async def status_summary(self) -> dict[str, Any]:
        pool = await self._ensure_pool()
        done = await pool.fetch(
            """
            SELECT item_id, dispatched_at, approval_item_id
            FROM runtime_dispatch_state
            WHERE dispatcher = $1 AND status = 'done'
            ORDER BY dispatched_at DESC NULLS LAST
            LIMIT 10
            """,
            self.dispatcher,
        )
        errors = await pool.fetch(
            """
            SELECT item_id, error, updated_at, retry_after, attempt
            FROM runtime_dispatch_state
            WHERE dispatcher = $1 AND status = 'error'
            ORDER BY updated_at DESC
            LIMIT 10
            """,
            self.dispatcher,
        )
        counts = await pool.fetchrow(
            """
            SELECT
              count(*) FILTER (WHERE status = 'done')    AS done,
              count(*) FILTER (WHERE status = 'error')   AS error,
              count(*) FILTER (WHERE status = 'claimed') AS claimed
            FROM runtime_dispatch_state
            WHERE dispatcher = $1
            """,
            self.dispatcher,
        )
        return {
            "backend": "postgres",
            "dispatched_count": counts["done"],
            "error_count": counts["error"],
            "claimed_count": counts["claimed"],
            "recent_dispatched": [
                {
                    "upload_id": r["item_id"],
                    "dispatched_at": (
                        r["dispatched_at"].isoformat()
                        if r["dispatched_at"]
                        else None
                    ),
                    "approval_item_id": r["approval_item_id"],
                }
                for r in done
            ],
            "recent_errors": [
                {
                    "upload_id": r["item_id"],
                    "error": r["error"],
                    "failed_at": (
                        r["updated_at"].isoformat() if r["updated_at"] else None
                    ),
                    "retry_after": (
                        r["retry_after"].isoformat() if r["retry_after"] else None
                    ),
                    "attempt": r["attempt"],
                }
                for r in errors
            ],
        }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def create_state_store(
    dispatcher: str,
    *,
    state_file: Path,
    dsn: str | None = None,
) -> DispatchStateStore:
    """Return the configured store for ``dispatcher``.

    Postgres when ``RUNTIME_STATE_DATABASE_URL`` (or explicit ``dsn``) is
    set; otherwise the legacy JSON file at ``state_file``.
    """
    effective = dsn or os.environ.get(_ENV_DSN) or ""
    if effective.strip():
        return PostgresStateStore(dispatcher, effective.strip())
    return FileStateStore(dispatcher, state_file)


def store_from_env(dispatcher: str) -> DispatchStateStore | None:
    """Postgres store if ``RUNTIME_STATE_DATABASE_URL`` is set, else None.

    The dispatchers keep their legacy JSON-file behavior when this returns
    None, so local dev / launchd / existing tests are untouched.
    """
    dsn = (os.environ.get(_ENV_DSN) or "").strip()
    if dsn:
        return PostgresStateStore(dispatcher, dsn)
    return None


__all__ = [
    "DispatchStateStore",
    "FileStateStore",
    "PostgresStateStore",
    "create_state_store",
    "store_from_env",
]
