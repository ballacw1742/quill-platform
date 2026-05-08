"""Offsite audit-log mirror.

Every successful AuditLogEntry write to Postgres is enqueued here. A background
task drains the queue and replicates each entry to Backblaze B2 (or, in dev,
to a local directory) at:

    {YYYY}/{MM}/{DD}/{approval_id_or_'global'}/{seq}.json

Object key encodes the entry's hash for idempotent dedup. Retention in prod
is set on the bucket itself (B2 Object Lock — compliance mode, 7-year period).

When B2 credentials are absent, falls back to local-disk mode (dev / CI).
Failures retry with exponential backoff. After max retries, the entry surfaces
through `get_status()` as `failed_entries` and emits a Sentry message (if
`app.services.sentry.capture_message` is importable; we soft-import to stay
decoupled from Sprint 2.4's parallel work).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import get_settings

log = logging.getLogger("quill.audit_mirror")


# ---------------------------------------------------------------------------
# Canonical JSON (must match app.services.audit._canonical exactly)
# ---------------------------------------------------------------------------
def canonical_json(payload: dict[str, Any]) -> str:
    """Deterministic JSON. Must be byte-identical to the audit-chain canonical
    serializer so the mirror's recomputed hash matches Postgres'.
    """

    def _default(o: Any) -> Any:
        if isinstance(o, datetime):
            return o.astimezone(UTC).isoformat()
        if hasattr(o, "value"):
            return o.value
        return str(o)

    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_default)


def entry_object_key(
    *,
    approval_item_id: str | None,
    seq: int,
    timestamp: datetime,
    entry_hash: str,
) -> str:
    """Stable, idempotent key. Embeds the hash so re-uploads are dedup-safe."""
    ts = timestamp.astimezone(UTC) if timestamp.tzinfo else timestamp.replace(tzinfo=UTC)
    bucket = approval_item_id or "global"
    short = entry_hash[:12]
    return (
        f"{ts.year:04d}/{ts.month:02d}/{ts.day:02d}/{bucket}/{seq:012d}-{short}.json"
    )


def entry_to_canonical_payload(entry: Any) -> dict[str, Any]:
    """Build the canonical payload mirrored to B2.

    Mirror payload contains the chain body + the recorded hash + linkage,
    so the mirror is self-verifying and self-describing.
    """
    ts = entry.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    else:
        ts = ts.astimezone(UTC)
    return {
        "id": entry.id,
        "event_type": entry.event_type,
        "actor": entry.actor,
        "approval_item_id": entry.approval_item_id,
        "payload": entry.payload,
        "timestamp": ts.isoformat(),
        "hash": entry.hash,
        "prev_hash": entry.prev_hash,
    }


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------
class _MirrorBackend:
    mode: str

    async def put(self, key: str, body: bytes) -> dict[str, Any]:
        raise NotImplementedError

    async def get(self, key: str) -> bytes | None:
        raise NotImplementedError

    async def list_keys(self, prefix: str = "") -> list[str]:
        raise NotImplementedError


class LocalDiskBackend(_MirrorBackend):
    """Writes to a local directory. Used when B2 creds are absent (dev/CI)."""

    mode = "local"

    def __init__(self, root: str | os.PathLike) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    async def put(self, key: str, body: bytes) -> dict[str, Any]:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        # Idempotent write (overwrite if same content; otherwise still overwrite —
        # the key embeds the hash so collisions are impossible across distinct entries).
        await asyncio.to_thread(path.write_bytes, body)
        return {"path": str(path), "size": len(body)}

    async def get(self, key: str) -> bytes | None:
        path = self.root / key
        if not path.exists():
            return None
        return await asyncio.to_thread(path.read_bytes)

    async def list_keys(self, prefix: str = "") -> list[str]:
        base = self.root
        prefix_path = base / prefix if prefix else base
        if not prefix_path.exists() and prefix:
            # prefix is a filter, not a literal dir
            prefix_path = base
        keys: list[str] = []
        if not base.exists():
            return keys

        def _walk() -> list[str]:
            out: list[str] = []
            for p in base.rglob("*.json"):
                rel = p.relative_to(base).as_posix()
                if not prefix or rel.startswith(prefix):
                    out.append(rel)
            out.sort()
            return out

        return await asyncio.to_thread(_walk)


class B2Backend(_MirrorBackend):
    """Backblaze B2 backend via b2sdk. All sync calls dispatched via to_thread."""

    mode = "b2"

    def __init__(self, key_id: str, app_key: str, bucket: str) -> None:
        from b2sdk.v2 import B2Api, InMemoryAccountInfo  # lazy import

        info = InMemoryAccountInfo()
        self._b2 = B2Api(info)
        self._b2.authorize_account("production", key_id, app_key)
        self._bucket = self._b2.get_bucket_by_name(bucket)
        self._bucket_name = bucket

    async def put(self, key: str, body: bytes) -> dict[str, Any]:
        def _upload() -> dict[str, Any]:
            sha1 = hashlib.sha1(body).hexdigest()
            file_info = self._bucket.upload_bytes(
                body,
                key,
                content_type="application/json",
                file_info={"sha256_chain_hash": hashlib.sha256(body).hexdigest()},
                sha1_sum=sha1,
            )
            return {
                "file_id": file_info.id_,
                "size": len(body),
                "bucket": self._bucket_name,
            }

        return await asyncio.to_thread(_upload)

    async def get(self, key: str) -> bytes | None:
        def _download() -> bytes | None:
            try:
                downloaded = self._bucket.download_file_by_name(key)
                buf = bytearray()
                downloaded.save(buf)  # type: ignore[arg-type]
                return bytes(buf)
            except Exception:  # noqa: BLE001
                return None

        return await asyncio.to_thread(_download)

    async def list_keys(self, prefix: str = "") -> list[str]:
        def _list() -> list[str]:
            out: list[str] = []
            for f, _ in self._bucket.ls(folder_to_list=prefix or "", recursive=True):
                if f.file_name.endswith(".json"):
                    out.append(f.file_name)
            out.sort()
            return out

        return await asyncio.to_thread(_list)


# ---------------------------------------------------------------------------
# Mirror service
# ---------------------------------------------------------------------------
@dataclass
class _PendingMirror:
    seq: int
    approval_item_id: str | None
    timestamp: datetime
    entry_hash: str
    canonical_body: bytes  # already serialized; safe to retry without DB access
    enqueued_at: float = field(default_factory=time.time)
    attempts: int = 0


@dataclass
class _MirrorStatus:
    mode: str = "local"
    bucket: str | None = None
    queue_depth: int = 0
    last_mirrored_at: datetime | None = None
    last_mirrored_seq: int | None = None
    last_error: str | None = None
    failed_entries: list[dict[str, Any]] = field(default_factory=list)
    total_mirrored: int = 0
    total_failed: int = 0


class AuditMirror:
    """Singleton-ish: one instance per process. Created in app lifespan.

    Tests reach in via `get_mirror()` to inspect status / drain manually.
    """

    def __init__(self, backend: _MirrorBackend, *, max_retries: int = 5) -> None:
        self._backend = backend
        self._queue: asyncio.Queue[_PendingMirror] = asyncio.Queue()
        self._status = _MirrorStatus(mode=backend.mode)
        if isinstance(backend, B2Backend):
            self._status.bucket = backend._bucket_name  # noqa: SLF001
        self._lock = threading.Lock()
        self._max_retries = max_retries
        self._worker_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        # Idempotency cache — last N hashes seen, prevents re-enqueue of the
        # same entry inside a single process lifetime.
        self._seen_hashes: set[str] = set()
        self._seen_order: list[str] = []
        self._seen_max = 4096

    # ── Public API ────────────────────────────────────────────────────────
    @property
    def backend(self) -> _MirrorBackend:
        return self._backend

    def enqueue(self, entry: Any) -> None:
        """Synchronously push an AuditLogEntry onto the mirror queue.

        Called from inside `record_event_with_mirror` after the Postgres flush.
        Safe to call from sync OR async context; we drop into the running loop.
        """
        if entry.hash in self._seen_hashes:
            return
        canonical_payload = entry_to_canonical_payload(entry)
        body = canonical_json(canonical_payload).encode("utf-8")
        pending = _PendingMirror(
            seq=int(entry.id),
            approval_item_id=entry.approval_item_id,
            timestamp=entry.timestamp,
            entry_hash=entry.hash,
            canonical_body=body,
        )
        with self._lock:
            self._seen_hashes.add(entry.hash)
            self._seen_order.append(entry.hash)
            if len(self._seen_order) > self._seen_max:
                evict = self._seen_order.pop(0)
                self._seen_hashes.discard(evict)
            self._status.queue_depth = self._queue.qsize() + 1
        # asyncio.Queue.put_nowait is sync-safe.
        self._queue.put_nowait(pending)

    async def drain(self, *, max_items: int | None = None) -> int:
        """Process up to `max_items` (or all) queued entries. Returns count mirrored.

        Used by tests; production uses `_run_worker`.
        """
        n = 0
        while not self._queue.empty() and (max_items is None or n < max_items):
            pending = self._queue.get_nowait()
            ok = await self._mirror_one(pending)
            self._queue.task_done()
            if ok:
                n += 1
        with self._lock:
            self._status.queue_depth = self._queue.qsize()
        return n

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            now = datetime.now(UTC)
            lag_seconds: float | None = None
            if self._status.last_mirrored_at is not None:
                # Lag here means "how stale is the last mirror confirmation",
                # i.e. wall time since last successful upload. That's the
                # operationally-useful number when the queue is empty.
                lag_seconds = (now - self._status.last_mirrored_at).total_seconds()
            return {
                "mode": self._status.mode,
                "bucket": self._status.bucket,
                "queue_depth": self._queue.qsize(),
                "last_mirrored_at": (
                    self._status.last_mirrored_at.isoformat()
                    if self._status.last_mirrored_at
                    else None
                ),
                "last_mirrored_seq": self._status.last_mirrored_seq,
                "last_error": self._status.last_error,
                "failed_entries": list(self._status.failed_entries),
                "total_mirrored": self._status.total_mirrored,
                "total_failed": self._status.total_failed,
                "lag_seconds": lag_seconds,
            }

    async def verify_entry(self, *, entry_hash: str, key: str) -> dict[str, Any]:
        """Fetch the mirrored object and confirm the hash matches.

        Returns {"ok": bool, "found": bool, "key": ..., "remote_hash": ...}.
        """
        body = await self._backend.get(key)
        if body is None:
            return {"ok": False, "found": False, "key": key, "remote_hash": None}
        try:
            doc = json.loads(body)
        except json.JSONDecodeError:
            return {"ok": False, "found": True, "key": key, "remote_hash": None}
        return {
            "ok": doc.get("hash") == entry_hash,
            "found": True,
            "key": key,
            "remote_hash": doc.get("hash"),
        }

    # ── Worker lifecycle ──────────────────────────────────────────────────
    async def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._stop.clear()
            self._worker_task = asyncio.create_task(self._run_worker(), name="audit-mirror-worker")
            log.info("audit_mirror worker started (mode=%s)", self._backend.mode)

    async def stop(self) -> None:
        self._stop.set()
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._worker_task = None

    async def _run_worker(self) -> None:
        settings = get_settings()
        interval = settings.AUDIT_MIRROR_DRAIN_INTERVAL_SECONDS
        while not self._stop.is_set():
            try:
                pending = await asyncio.wait_for(self._queue.get(), timeout=interval)
            except TimeoutError:
                continue
            try:
                await self._mirror_one(pending)
            finally:
                self._queue.task_done()

    # ── Mirror execution ─────────────────────────────────────────────────
    async def _mirror_one(self, pending: _PendingMirror) -> bool:
        key = entry_object_key(
            approval_item_id=pending.approval_item_id,
            seq=pending.seq,
            timestamp=pending.timestamp,
            entry_hash=pending.entry_hash,
        )
        for attempt in range(1, self._max_retries + 1):
            pending.attempts = attempt
            try:
                await self._backend.put(key, pending.canonical_body)
                with self._lock:
                    self._status.last_mirrored_at = datetime.now(UTC)
                    self._status.last_mirrored_seq = pending.seq
                    self._status.last_error = None
                    self._status.total_mirrored += 1
                    self._status.queue_depth = self._queue.qsize()
                log.debug("audit_mirror put ok seq=%s key=%s attempt=%s", pending.seq, key, attempt)
                return True
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._status.last_error = f"{type(exc).__name__}: {exc}"
                log.warning(
                    "audit_mirror put failed seq=%s attempt=%s err=%s",
                    pending.seq, attempt, exc,
                )
                if attempt < self._max_retries:
                    backoff = min(30.0, 0.25 * (2 ** (attempt - 1)))
                    await asyncio.sleep(backoff)

        # Exceeded retries — surface
        with self._lock:
            self._status.total_failed += 1
            self._status.failed_entries.append(
                {
                    "seq": pending.seq,
                    "key": key,
                    "hash": pending.entry_hash,
                    "approval_item_id": pending.approval_item_id,
                    "attempts": pending.attempts,
                    "last_error": self._status.last_error,
                }
            )
            # Keep failed_entries bounded — the freeze flag is the durable signal.
            if len(self._status.failed_entries) > 200:
                self._status.failed_entries = self._status.failed_entries[-200:]
        _emit_sentry(
            "audit_mirror replication failed after retries",
            seq=pending.seq,
            entry_hash=pending.entry_hash,
            approval_item_id=pending.approval_item_id,
        )
        return False


# ---------------------------------------------------------------------------
# Sentry soft-import helper
# ---------------------------------------------------------------------------
def _emit_sentry(message: str, **tags: Any) -> None:
    try:
        from app.services import sentry as _sentry  # type: ignore

        if hasattr(_sentry, "capture_message"):
            _sentry.capture_message(message, level="error", **tags)
            return
    except Exception:  # noqa: BLE001
        pass
    try:
        import sentry_sdk

        sentry_sdk.capture_message(message, level="error")
    except Exception:  # noqa: BLE001
        log.error("audit_mirror could not raise sentry: %s tags=%s", message, tags)


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------
_MIRROR: AuditMirror | None = None
_MIRROR_LOCK = threading.Lock()


def build_backend() -> _MirrorBackend:
    s = get_settings()
    if s.B2_KEY_ID and s.B2_APPLICATION_KEY and s.B2_BUCKET:
        try:
            return B2Backend(s.B2_KEY_ID, s.B2_APPLICATION_KEY, s.B2_BUCKET)
        except Exception as exc:  # noqa: BLE001
            log.warning("audit_mirror B2 init failed (%s); falling back to local", exc)
    return LocalDiskBackend(s.AUDIT_MIRROR_LOCAL_PATH)


def get_mirror() -> AuditMirror:
    global _MIRROR
    with _MIRROR_LOCK:
        if _MIRROR is None:
            backend = build_backend()
            s = get_settings()
            _MIRROR = AuditMirror(backend, max_retries=s.AUDIT_MIRROR_MAX_RETRIES)
        return _MIRROR


def reset_mirror_for_tests() -> None:
    """Tests that want a fresh queue/backend call this between cases."""
    global _MIRROR
    with _MIRROR_LOCK:
        _MIRROR = None


__all__ = [
    "AuditMirror",
    "B2Backend",
    "LocalDiskBackend",
    "build_backend",
    "canonical_json",
    "entry_object_key",
    "entry_to_canonical_payload",
    "get_mirror",
    "reset_mirror_for_tests",
]
