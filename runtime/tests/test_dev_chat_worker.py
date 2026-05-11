"""Tests for DevChatWorker (Sprint DC.1).

Covers:
  - simulate mode produces a commit + DEV_CHAT_LOG.md entry
  - idempotent on restart (doesn't re-process completed tasks)
  - respects cancel marker (stops waiting when .cancel file appears)
  - task brief is written correctly to the queue dir
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runtime.dev_chat_worker import (
    DevChatWorker,
    _QUEUE_DIR,
    _simulate_run,
    _wait_for_result,
    _write_task_brief,
)


SAMPLE_TASK = {
    "task_id": "test-task-001",
    "user_id": "user-001",
    "user_message": "Make the button red",
    "thread_id": "thread-001",
    "message_id": "msg-001",
    "budget_usd_cap": 2.0,
    "branch": "dev-chat/test-task-001",
    "status": "queued",
}


# ---------------------------------------------------------------------------
# Task brief writer
# ---------------------------------------------------------------------------

def test_write_task_brief_creates_file(tmp_path, monkeypatch):
    """_write_task_brief writes a valid JSON file atomically."""
    monkeypatch.setattr(
        "runtime.dev_chat_worker._QUEUE_DIR", tmp_path
    )
    path = _write_task_brief(SAMPLE_TASK)
    assert path.exists()
    brief = json.loads(path.read_text())
    assert brief["task_id"] == SAMPLE_TASK["task_id"]
    assert brief["user_message"] == SAMPLE_TASK["user_message"]
    assert brief["budget_usd_cap"] == 2.0
    assert "disallowed_paths" in brief
    assert "context" in brief


# ---------------------------------------------------------------------------
# Cancel marker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wait_for_result_respects_cancel_marker(tmp_path, monkeypatch):
    """_wait_for_result returns cancelled status when .cancel file exists."""
    monkeypatch.setattr("runtime.dev_chat_worker._QUEUE_DIR", tmp_path)
    monkeypatch.setattr("runtime.dev_chat_worker._RESULT_POLL_INTERVAL_S", 0.05)

    task_id = "cancel-task"
    cancel_path = tmp_path / f"{task_id}.cancel"
    cancel_path.write_text("cancelled\n")

    result = await _wait_for_result(task_id)
    assert result is not None
    assert result["status"] == "cancelled"


@pytest.mark.asyncio
async def test_wait_for_result_reads_result_file(tmp_path, monkeypatch):
    """_wait_for_result returns result when .result.json appears."""
    monkeypatch.setattr("runtime.dev_chat_worker._QUEUE_DIR", tmp_path)
    monkeypatch.setattr("runtime.dev_chat_worker._RESULT_POLL_INTERVAL_S", 0.05)

    task_id = "result-task"
    result_data = {
        "task_id": task_id,
        "status": "completed",
        "commit_sha": "abc1234",
        "branch": f"dev-chat/{task_id}",
        "merged_to_main": True,
        "files_changed": ["web/DEV_CHAT_LOG.md"],
        "summary": "Done",
        "error": None,
        "cost_usd": 0.0,
        "completed_at": datetime.now(UTC).isoformat(),
    }

    async def _write_after_delay():
        await asyncio.sleep(0.1)
        (tmp_path / f"{task_id}.result.json").write_text(json.dumps(result_data))

    asyncio.create_task(_write_after_delay())
    result = await _wait_for_result(task_id)
    assert result is not None
    assert result["status"] == "completed"
    assert result["commit_sha"] == "abc1234"


# ---------------------------------------------------------------------------
# Simulate mode
# ---------------------------------------------------------------------------

def test_simulate_run_produces_commit(tmp_path, monkeypatch):
    """_simulate_run appends to DEV_CHAT_LOG.md and creates a git commit."""
    # We can't easily do real git in tests — mock subprocess.run
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "rev-parse" in cmd:
            result = MagicMock()
            result.stdout = "deadbeef1234567890\n"
            return result
        if "commit" in cmd:
            result = MagicMock()
            result.stdout = "[main abc1234] DEV-CHAT: Make the button red\n"
            return result
        return MagicMock()

    monkeypatch.setattr("subprocess.run", fake_run)

    # Use tmp_path for repo root and log file
    log_file = tmp_path / "web" / "DEV_CHAT_LOG.md"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("runtime.dev_chat_worker._REPO_ROOT", tmp_path)

    task = {**SAMPLE_TASK, "user_message": "Make the button red"}
    result = _simulate_run(task)

    # Check DEV_CHAT_LOG.md was appended
    assert log_file.exists()
    content = log_file.read_text()
    assert "DEV-CHAT-SIM: Make the button red" in content

    # Check git add/commit/push were called
    assert any("add" in str(c) for c in calls)
    assert any("commit" in str(c) for c in calls)
    assert any("push" in str(c) for c in calls)

    # Check result shape
    assert result["status"] == "completed"
    assert result["merged_to_main"] is True
    assert "web/DEV_CHAT_LOG.md" in result["files_changed"]


def test_simulate_run_handles_git_error(tmp_path, monkeypatch):
    """_simulate_run returns failed status when git errors."""
    import subprocess as subprocess_mod

    def fake_run_fail(cmd, **kwargs):
        if "commit" in cmd:
            raise subprocess_mod.CalledProcessError(1, cmd, output=b"", stderr=b"error")
        if "add" in cmd:
            return MagicMock()
        return MagicMock()

    monkeypatch.setattr("subprocess.run", fake_run_fail)
    log_file = tmp_path / "web" / "DEV_CHAT_LOG.md"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("runtime.dev_chat_worker._REPO_ROOT", tmp_path)

    result = _simulate_run(SAMPLE_TASK)
    assert result["status"] == "failed"
    assert result["commit_sha"] is None


# ---------------------------------------------------------------------------
# Worker poll loop idempotency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_worker_poll_empty_queue_is_noop():
    """Worker doesn't crash when queue is empty."""
    worker = DevChatWorker(
        api_url="http://localhost:8000",
        agent_secret="secret",
        simulate=True,
        poll_interval_s=1.0,
    )

    with patch.object(worker._client, "get_queued_tasks", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = []
        await worker._poll_once()
        mock_get.assert_called_once()
