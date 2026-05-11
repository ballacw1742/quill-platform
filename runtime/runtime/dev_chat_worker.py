"""DevChatWorker — Sprint DC.1.

Polls ``dev_chat_tasks WHERE status='queued'`` and dispatches OpenClaw
sub-agent task briefs.

==========================================================================
INTEGRATION CONTRACT FOR THE OPENCLAW BRIDGE
==========================================================================

The worker communicates with OpenClaw via the file-based queue protocol
below.  The bridge (a future Axe/OpenClaw task that watches the queue
directory) must implement the read side.

Queue directory
---------------
    ~/.openclaw/dev-chat-queue/

Files written by the worker (→ read by OpenClaw)
-------------------------------------------------
``<task_id>.task.json``
    The task brief.  Written atomically (tmp→rename) before the worker
    transitions the DB task to ``running``.  Shape::

        {
          "task_id": "uuid",
          "user_id": "uuid",
          "user_message": "Make the cost table description column wider",
          "branch": "dev-chat/<task_id>",
          "budget_usd_cap": 2.0,
          "disallowed_paths": [
            "api/app/security.py", "api/app/auth/**", ".env", ...
          ],
          "context": {
            "repo_path": "/Users/charlesmitchell/.openclaw/workspace/quill-platform",
            "thread_id": "uuid"
          },
          "requested_at": "2026-05-10T21:00:00+00:00"
        }

Files written by OpenClaw (→ read by the worker)
-------------------------------------------------
``<task_id>.result.json``
    Written when the sub-agent finishes.  Shape::

        {
          "task_id": "uuid",
          "status": "completed" | "failed" | "cancelled",
          "commit_sha": "abc1234..." | null,
          "branch": "dev-chat/<task_id>",
          "merged_to_main": true | false,
          "files_changed": ["web/components/..."],
          "summary": "Short human-readable summary",
          "error": "..." | null,
          "cost_usd": 0.42,
          "completed_at": "2026-05-10T21:05:00+00:00"
        }

``<task_id>.progress.jsonl``  (append-only)
    Progress events tailed by the worker and broadcast via WS.  Shape per
    line::

        {"ts": "ISO", "kind": "status"|"edit"|"error", "message": "..."}

``<task_id>.cancel``
    Created by the API /cancel endpoint.  Worker treats this as a signal
    to abort and write a result.json with status=cancelled.

Timing assumptions
------------------
- Task brief is written before the DB record transitions to ``running``.
  OpenClaw MUST NOT rely on the task being in ``running`` state before it
  starts — check the file, not the DB.
- The worker polls for result.json every 3 seconds.
- Timeout: 90 minutes.  After timeout the worker writes status=failed.
- Progress lines are processed immediately as they appear (tail-follow).
- The cancel file is checked every 3 seconds alongside result.json.

Simulate mode (--simulate-agent)
---------------------------------
When the CLI is started with ``--simulate-agent``, the worker:
1. Appends a line to ``web/DEV_CHAT_LOG.md`` in the repo root.
2. Creates a git commit with the user message as the body.
3. Pushes to ``origin/main``.
4. Writes a synthetic result.json with status=completed.

This lets end-to-end smoke tests run without wiring up OpenClaw.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_QUEUE_DIR = Path.home() / ".openclaw" / "dev-chat-queue"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_POLL_INTERVAL_S = 5.0
_RESULT_POLL_INTERVAL_S = 3.0
_MAX_WAIT_S = 90 * 60  # 90 minutes

_DISALLOWED_PATHS: list[str] = [
    "api/app/security.py",
    "api/app/auth/**",
    ".env",
    "**/.env*",
    "alembic/**",
    "deployment/**",
    "scripts/restart*",
]


# ---------------------------------------------------------------------------
# HTTP client helpers (talks to the Quill API)
# ---------------------------------------------------------------------------

class _ApiClient:
    """Thin async HTTP wrapper around the Quill API."""

    def __init__(self, base_url: str, secret: str) -> None:
        self._base = base_url.rstrip("/")
        self._secret = secret

    def _headers(self) -> dict[str, str]:
        return {
            "X-Agent-Secret": self._secret,
            "Content-Type": "application/json",
        }

    async def get_queued_tasks(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{self._base}/v1/dev-chat/worker/queued", headers=self._headers())
            r.raise_for_status()
            return r.json()

    async def mark_running(self, task_id: str) -> None:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.patch(
                f"{self._base}/v1/dev-chat/worker/tasks/{task_id}/running",
                headers=self._headers(),
            )
            r.raise_for_status()

    async def complete_task(self, task_id: str, payload: dict[str, Any]) -> None:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.patch(
                f"{self._base}/v1/dev-chat/worker/tasks/{task_id}/complete",
                headers=self._headers(),
                content=json.dumps(payload),
            )
            r.raise_for_status()

    async def add_progress_message(self, task_id: str, thread_id: str, message: str) -> None:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                f"{self._base}/v1/dev-chat/worker/tasks/{task_id}/progress",
                headers=self._headers(),
                content=json.dumps({"thread_id": thread_id, "message": message}),
            )
            # Non-fatal; don't raise on progress errors
            if r.status_code >= 500:
                log.warning("progress push failed", task_id=task_id, status=r.status_code)


# ---------------------------------------------------------------------------
# Task brief writer
# ---------------------------------------------------------------------------

def _write_task_brief(task: dict[str, Any]) -> Path:
    """Atomically write the task brief JSON to the queue dir."""
    _QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    task_id = task["task_id"]
    brief = {
        "task_id": task_id,
        "user_id": task["user_id"],
        "user_message": task["user_message"],
        "branch": f"dev-chat/{task_id}",
        "budget_usd_cap": float(task.get("budget_usd_cap", 2.0)),
        "disallowed_paths": _DISALLOWED_PATHS,
        "context": {
            "repo_path": str(_REPO_ROOT),
            "thread_id": task["thread_id"],
        },
        "requested_at": datetime.now(UTC).isoformat(),
    }
    dest = _QUEUE_DIR / f"{task_id}.task.json"
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(brief, indent=2), encoding="utf-8")
    tmp.rename(dest)
    log.info("task brief written", task_id=task_id, path=str(dest))
    return dest


# ---------------------------------------------------------------------------
# Simulate mode
# ---------------------------------------------------------------------------

def _simulate_run(task: dict[str, Any]) -> dict[str, Any]:
    """Simulate a successful agent run without calling OpenClaw."""
    task_id = task["task_id"]
    user_message = task["user_message"]

    # 1. Append to DEV_CHAT_LOG.md
    log_file = _REPO_ROOT / "web" / "DEV_CHAT_LOG.md"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).isoformat()
    entry = f"\n## {ts}\n\nDEV-CHAT-SIM: {user_message}\n"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(entry)

    # 2. Git commit + push
    repo = str(_REPO_ROOT)
    try:
        subprocess.run(["git", "add", str(log_file)], cwd=repo, check=True, capture_output=True)
        commit_msg = f"DEV-CHAT: {user_message[:72]}"
        result = subprocess.run(
            ["git", "commit", "-m", commit_msg, "--allow-empty"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        # Get commit SHA
        sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        commit_sha = sha_result.stdout.strip()

        # Push to origin/main
        subprocess.run(
            ["git", "push", "origin", "HEAD:main"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        log.error("simulate git error", error=str(e), stderr=e.stderr if hasattr(e, "stderr") else "")
        commit_sha = None
        return {
            "task_id": task_id,
            "status": "failed",
            "commit_sha": None,
            "branch": f"dev-chat/{task_id}",
            "merged_to_main": False,
            "files_changed": [],
            "summary": f"Simulate git error: {e}",
            "error": str(e),
            "cost_usd": 0.0,
            "completed_at": datetime.now(UTC).isoformat(),
        }

    return {
        "task_id": task_id,
        "status": "completed",
        "commit_sha": commit_sha,
        "branch": "main",
        "merged_to_main": True,
        "files_changed": ["web/DEV_CHAT_LOG.md"],
        "summary": f"Simulated: {user_message[:80]}",
        "error": None,
        "cost_usd": 0.0,
        "completed_at": datetime.now(UTC).isoformat(),
    }


# ---------------------------------------------------------------------------
# Production mode: wait for result file
# ---------------------------------------------------------------------------

async def _wait_for_result(task_id: str) -> dict[str, Any] | None:
    """Poll for result.json or .cancel marker.  Returns result dict or None on timeout."""
    result_path = _QUEUE_DIR / f"{task_id}.result.json"
    cancel_path = _QUEUE_DIR / f"{task_id}.cancel"
    progress_path = _QUEUE_DIR / f"{task_id}.progress.jsonl"

    elapsed = 0.0
    progress_offset = 0

    while elapsed < _MAX_WAIT_S:
        # Check cancel
        if cancel_path.exists():
            log.info("cancel marker found", task_id=task_id)
            return {
                "task_id": task_id,
                "status": "cancelled",
                "commit_sha": None,
                "branch": f"dev-chat/{task_id}",
                "merged_to_main": False,
                "files_changed": [],
                "summary": "Cancelled by user",
                "error": None,
                "cost_usd": 0.0,
                "completed_at": datetime.now(UTC).isoformat(),
            }

        # Tail progress.jsonl
        if progress_path.exists():
            lines = progress_path.read_text(encoding="utf-8").splitlines()
            for line in lines[progress_offset:]:
                line = line.strip()
                if line:
                    try:
                        _evt = json.loads(line)
                        log.info("progress", task_id=task_id, event=_evt)
                    except Exception:
                        pass
                    progress_offset += 1

        # Check result
        if result_path.exists():
            try:
                return json.loads(result_path.read_text(encoding="utf-8"))
            except Exception as e:
                log.error("malformed result.json", task_id=task_id, error=str(e))
                break

        await asyncio.sleep(_RESULT_POLL_INTERVAL_S)
        elapsed += _RESULT_POLL_INTERVAL_S

    # Timeout
    return None


# ---------------------------------------------------------------------------
# DevChatWorker
# ---------------------------------------------------------------------------

class DevChatWorker:
    """Polls the DB for queued dev-chat tasks and dispatches them.

    In simulate mode: handles the full run locally (no OpenClaw).
    In production mode: writes a task brief and waits for OpenClaw to
    write a result file.

    The worker calls the Quill API to update task/message state rather
    than accessing the DB directly, so it can run out-of-process.
    """

    def __init__(
        self,
        *,
        api_url: str | None = None,
        agent_secret: str | None = None,
        simulate: bool = False,
        poll_interval_s: float = _POLL_INTERVAL_S,
    ) -> None:
        self._api_url = (api_url or os.environ.get("QUILL_API_URL", "http://localhost:8000")).rstrip("/")
        self._secret = agent_secret or os.environ.get("AGENT_SHARED_SECRET", "dev-agent-secret-change-me")
        self._simulate = simulate
        self._poll_interval_s = poll_interval_s
        self._running = True
        self._client = _ApiClient(self._api_url, self._secret)

    def stop(self) -> None:
        self._running = False

    async def start(self) -> None:
        mode = "simulate" if self._simulate else "production"
        log.info("DevChatWorker starting", mode=mode, api=self._api_url, poll_interval=self._poll_interval_s)
        _QUEUE_DIR.mkdir(parents=True, exist_ok=True)

        while self._running:
            try:
                await self._poll_once()
            except Exception as e:
                log.error("poll error", error=str(e), exc_info=True)
            await asyncio.sleep(self._poll_interval_s)

    async def _poll_once(self) -> None:
        try:
            tasks = await self._client.get_queued_tasks()
        except Exception as e:
            log.warning("failed to fetch queued tasks", error=str(e))
            return

        for task in tasks:
            asyncio.create_task(self._handle_task(task))

    async def _handle_task(self, task: dict[str, Any]) -> None:
        task_id = task["task_id"]
        log.info("handling task", task_id=task_id, simulate=self._simulate)

        try:
            # Mark running
            await self._client.mark_running(task_id)

            # Write brief
            _write_task_brief(task)

            if self._simulate:
                # Run synchronously in executor to avoid blocking the event loop on git
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, _simulate_run, task)
            else:
                result = await _wait_for_result(task_id)
                if result is None:
                    result = {
                        "task_id": task_id,
                        "status": "failed",
                        "commit_sha": None,
                        "branch": f"dev-chat/{task_id}",
                        "merged_to_main": False,
                        "files_changed": [],
                        "summary": "Timed out waiting for agent result",
                        "error": "90-minute timeout exceeded",
                        "cost_usd": 0.0,
                        "completed_at": datetime.now(UTC).isoformat(),
                    }

            await self._client.complete_task(task_id, result)
            log.info("task complete", task_id=task_id, status=result.get("status"))

        except Exception as e:
            log.error("task handler error", task_id=task_id, error=str(e), exc_info=True)
            try:
                await self._client.complete_task(task_id, {
                    "task_id": task_id,
                    "status": "failed",
                    "commit_sha": None,
                    "branch": f"dev-chat/{task_id}",
                    "merged_to_main": False,
                    "files_changed": [],
                    "summary": "Internal worker error",
                    "error": str(e),
                    "cost_usd": 0.0,
                    "completed_at": datetime.now(UTC).isoformat(),
                })
            except Exception:
                pass
