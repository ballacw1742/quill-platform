"""Tests for runtime.state_store (Sprint 5.5 — GCP worker state)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from runtime.state_store import (
    FileStateStore,
    PostgresStateStore,
    _parse_pg_dsn,
    create_state_store,
    store_from_env,
)

# ---------------------------------------------------------------------------
# DSN parsing
# ---------------------------------------------------------------------------
class TestParsePgDsn:
    def test_cloud_sql_unix_socket_sqlalchemy_url(self) -> None:
        dsn = (
            "postgresql+asyncpg://postgres:s3cr%40t@/quill"
            "?host=/cloudsql/proj-1:us-central1:my-db"
        )
        kwargs = _parse_pg_dsn(dsn)
        assert kwargs["user"] == "postgres"
        assert kwargs["password"] == "s3cr@t"
        assert kwargs["database"] == "quill"
        assert kwargs["host"] == "/cloudsql/proj-1:us-central1:my-db"

    def test_plain_tcp_url(self) -> None:
        kwargs = _parse_pg_dsn("postgresql://u:p@db.example.com:5433/mydb")
        assert kwargs == {
            "user": "u",
            "password": "p",
            "database": "mydb",
            "host": "db.example.com",
            "port": 5433,
        }

    def test_no_credentials(self) -> None:
        kwargs = _parse_pg_dsn("postgresql://localhost/quill")
        assert kwargs["host"] == "localhost"
        assert kwargs["database"] == "quill"
        assert "user" not in kwargs


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
class TestFactory:
    def test_default_is_file(self, tmp_path: Path, monkeypatch: Any) -> None:
        monkeypatch.delenv("RUNTIME_STATE_DATABASE_URL", raising=False)
        store = create_state_store("contract", state_file=tmp_path / "s.json")
        assert isinstance(store, FileStateStore)

    def test_env_dsn_selects_postgres(self, tmp_path: Path, monkeypatch: Any) -> None:
        monkeypatch.setenv(
            "RUNTIME_STATE_DATABASE_URL", "postgresql://u:p@localhost/db"
        )
        store = create_state_store("contract", state_file=tmp_path / "s.json")
        assert isinstance(store, PostgresStateStore)

    def test_store_from_env_none_by_default(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("RUNTIME_STATE_DATABASE_URL", raising=False)
        assert store_from_env("contract") is None

    def test_store_from_env_postgres(self, monkeypatch: Any) -> None:
        monkeypatch.setenv(
            "RUNTIME_STATE_DATABASE_URL", "postgresql://u:p@localhost/db"
        )
        store = store_from_env("estimator")
        assert isinstance(store, PostgresStateStore)
        assert store.dispatcher == "estimator"


# ---------------------------------------------------------------------------
# FileStateStore — legacy schema compatibility + claim semantics
# ---------------------------------------------------------------------------
class TestFileStateStore:
    async def test_claim_then_success_is_terminal(self, tmp_path: Path) -> None:
        store = FileStateStore("contract", tmp_path / "s.json")
        assert await store.try_claim("u1") is True
        await store.record_success("u1", "appr-1")
        assert await store.try_claim("u1") is False
        assert await store.is_done("u1") is True

    async def test_error_backoff_blocks_reclaim(self, tmp_path: Path) -> None:
        store = FileStateStore("contract", tmp_path / "s.json")
        await store.record_error("u1", "boom")
        # First failure → retry_after 30s in the future → not claimable.
        assert await store.try_claim("u1") is False
        assert await store.is_done("u1") is False

    async def test_error_retryable_after_backoff(self, tmp_path: Path) -> None:
        store = FileStateStore("contract", tmp_path / "s.json")
        await store.record_error("u1", "boom")
        # Rewind retry_after so it's in the past.
        entry = store._error_entry("u1")
        assert entry is not None
        entry.retry_after = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        assert await store.try_claim("u1") is True

    async def test_persists_legacy_json_schema(self, tmp_path: Path) -> None:
        sf = tmp_path / "s.json"
        store = FileStateStore("contract", sf)
        await store.record_success("u1", "appr-9")
        await store.record_error("u2", "kaput")
        raw = json.loads(sf.read_text(encoding="utf-8"))
        # Exact legacy shape: dispatched map + errors list w/ upload_id keys.
        assert raw["dispatched"]["u1"]["approval_item_id"] == "appr-9"
        assert raw["errors"][0]["upload_id"] == "u2"
        assert raw["errors"][0]["attempt"] == 1
        assert "retry_after" in raw["errors"][0]

    async def test_reads_legacy_file_written_by_old_dispatchers(
        self, tmp_path: Path
    ) -> None:
        sf = tmp_path / "s.json"
        sf.write_text(
            json.dumps(
                {
                    "dispatched": {
                        "old-1": {
                            "dispatched_at": "2026-07-01T00:00:00+00:00",
                            "approval_item_id": "a-1",
                        }
                    },
                    "errors": [
                        {
                            "upload_id": "old-2",
                            "error": "x",
                            "failed_at": "2026-07-01T00:00:00+00:00",
                            "retry_after": "2026-07-01T00:00:30+00:00",
                            "attempt": 2,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        store = FileStateStore("contract", sf)
        assert await store.is_done("old-1") is True
        assert await store.try_claim("old-1") is False
        # old-2's retry_after is long past → claimable again.
        assert await store.try_claim("old-2") is True

    async def test_error_attempt_escalates(self, tmp_path: Path) -> None:
        store = FileStateStore("contract", tmp_path / "s.json")
        await store.record_error("u1", "one")
        await store.record_error("u1", "two")
        entry = store._error_entry("u1")
        assert entry is not None and entry.attempt == 2

    async def test_success_clears_error(self, tmp_path: Path) -> None:
        store = FileStateStore("contract", tmp_path / "s.json")
        await store.record_error("u1", "one")
        await store.record_success("u1", None)
        assert store._error_entry("u1") is None
        assert await store.is_done("u1") is True

    async def test_status_summary(self, tmp_path: Path) -> None:
        store = FileStateStore("contract", tmp_path / "s.json")
        await store.record_success("u1", "a-1")
        await store.record_error("u2", "err")
        summary = await store.status_summary()
        assert summary["backend"] == "file"
        assert summary["dispatched_count"] == 1
        assert summary["error_count"] == 1
        assert summary["recent_dispatched"][0]["upload_id"] == "u1"
        assert summary["recent_errors"][0]["upload_id"] == "u2"

    async def test_release_claim_is_noop(self, tmp_path: Path) -> None:
        store = FileStateStore("contract", tmp_path / "s.json")
        assert await store.try_claim("u1") is True
        await store.release_claim("u1")
        assert await store.try_claim("u1") is True


# ---------------------------------------------------------------------------
# Dispatcher wiring — store mode routes through claim/unclaim/mark seam
# ---------------------------------------------------------------------------
class _RecordingStore:
    """In-memory DispatchStateStore double that records calls."""

    dispatcher = "contract"

    def __init__(self) -> None:
        self.done: dict[str, str | None] = {}
        self.errors: dict[str, str] = {}
        self.claimed: set[str] = set()
        self.released: list[str] = []
        self.setup_called = False

    async def setup(self) -> None:
        self.setup_called = True

    async def aclose(self) -> None:
        pass

    async def is_done(self, item_id: str) -> bool:
        return item_id in self.done

    async def try_claim(self, item_id: str) -> bool:
        if item_id in self.done or item_id in self.claimed:
            return False
        self.claimed.add(item_id)
        return True

    async def release_claim(self, item_id: str) -> None:
        self.claimed.discard(item_id)
        self.released.append(item_id)

    async def record_success(self, item_id: str, approval_item_id: str | None) -> None:
        self.claimed.discard(item_id)
        self.done[item_id] = approval_item_id

    async def record_error(self, item_id: str, error: str) -> None:
        self.claimed.discard(item_id)
        self.errors[item_id] = error

    async def status_summary(self) -> dict[str, Any]:
        return {"backend": "fake"}


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


class TestDispatcherStoreWiring:
    """ContractDispatcher._tick with an injected store: claim → guard → mark."""

    def _dispatcher(self, tmp_path: Path, store: _RecordingStore):
        from runtime.config import Config
        from runtime.contract_dispatcher import ContractDispatcher

        cfg = Config(
            prompts_repo_path=tmp_path,
            queue_api_url="http://test.invalid",
            agent_shared_secret="s",
        )
        return ContractDispatcher(
            config=cfg,
            state_file=tmp_path / "state.json",
            dispatch_requests_dir=tmp_path / "requests",
            state_store=store,  # injected — no env needed
        )

    async def test_guard_already_extracted_marks_done(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        import runtime.contract_dispatcher as cd

        store = _RecordingStore()
        dispatcher = self._dispatcher(tmp_path, store)

        async def fake_list(client, config, limit=50):
            return [{"upload_id": "u1"}]

        async def fake_fetch(client, config, upload_id):
            return {"upload_id": "u1", "status": "extracted", "extracted_fields": {"a": 1}}

        monkeypatch.setattr(cd, "_fetch_extracted_contracts", fake_list)
        monkeypatch.setattr(cd, "_fetch_contract", fake_fetch)

        await dispatcher._tick(http_client=None, queue_client=None)
        assert store.done == {"u1": None}

    async def test_guard_not_ready_releases_claim(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        import runtime.contract_dispatcher as cd

        store = _RecordingStore()
        dispatcher = self._dispatcher(tmp_path, store)

        async def fake_list(client, config, limit=50):
            return [{"upload_id": "u1"}]

        async def fake_fetch(client, config, upload_id):
            return {"upload_id": "u1", "status": "uploaded", "extracted_fields": None}

        monkeypatch.setattr(cd, "_fetch_extracted_contracts", fake_list)
        monkeypatch.setattr(cd, "_fetch_contract", fake_fetch)

        await dispatcher._tick(http_client=None, queue_client=None)
        assert "u1" in store.released
        assert store.done == {}

    async def test_dispatch_error_records_error(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        import runtime.contract_dispatcher as cd

        store = _RecordingStore()
        dispatcher = self._dispatcher(tmp_path, store)

        async def fake_list(client, config, limit=50):
            return [{"upload_id": "u1"}]

        async def fake_fetch(client, config, upload_id):
            return {"upload_id": "u1", "status": "extracted", "extracted_fields": None}

        async def fake_dispatch_one(*args: Any, **kwargs: Any):
            raise RuntimeError("llm exploded")

        monkeypatch.setattr(cd, "_fetch_extracted_contracts", fake_list)
        monkeypatch.setattr(cd, "_fetch_contract", fake_fetch)
        monkeypatch.setattr(cd, "dispatch_one", fake_dispatch_one)

        await dispatcher._tick(http_client=None, queue_client=None)
        assert "u1" in store.errors
        assert "llm exploded" in store.errors["u1"]

    async def test_already_done_skips_and_cleans_marker(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        import runtime.contract_dispatcher as cd

        store = _RecordingStore()
        store.done["u1"] = "appr-1"
        dispatcher = self._dispatcher(tmp_path, store)
        # Priority marker present → should be removed for done items.
        marker_dir = tmp_path / "requests"
        marker_dir.mkdir()
        (marker_dir / "u1.json").write_text("{}", encoding="utf-8")

        async def fake_list(client, config, limit=50):
            return [{"upload_id": "u1"}]

        fetch_calls: list[str] = []

        async def fake_fetch(client, config, upload_id):
            fetch_calls.append(upload_id)
            return None

        monkeypatch.setattr(cd, "_fetch_extracted_contracts", fake_list)
        monkeypatch.setattr(cd, "_fetch_contract", fake_fetch)

        await dispatcher._tick(http_client=None, queue_client=None)
        assert fetch_calls == []  # never re-fetched a done item
        assert not (marker_dir / "u1.json").exists()
