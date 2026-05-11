"""RedeployWatcher — Sprint DC.1.

Watches ``git log -1 origin/main`` for new commits on main.  When a new
SHA appears, it pulls the latest code and runs ``make restart-all``.

Design goals (mirrors ClassificationDispatcher):
- **Idempotent.** State (last deployed SHA) persists across restarts.
- **Crash-safe.** SHA written atomically (tmp→rename).
- **Graceful shutdown.** Handles SIGTERM / SIGINT cleanly.
- **Eager deploy.** On startup, if the stored SHA differs from the current
  origin/main SHA, deploys immediately before entering the poll loop.

State file:
    ``runtime/_state/last_deployed_sha.txt``

Configuration:
    ``REDEPLOY_POLL_INTERVAL_SECONDS`` (env, default 30)
    ``QUILL_REPO_PATH`` (env, default: auto-detected as the repo root)
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

_STATE_FILE = Path(__file__).resolve().parents[2] / "_state" / "last_deployed_sha.txt"
_DEFAULT_POLL_INTERVAL_S = 30.0
_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _repo_path() -> Path:
    """Return the repo root.  Prefer QUILL_REPO_PATH env var."""
    env = os.environ.get("QUILL_REPO_PATH")
    if env:
        return Path(env)
    return _REPO_ROOT


def _git_remote_sha(repo: Path) -> str | None:
    """Fetch + return current HEAD SHA on origin/main."""
    try:
        subprocess.run(
            ["git", "fetch", "origin", "main", "--quiet"],
            cwd=str(repo),
            check=True,
            capture_output=True,
            timeout=60,
        )
        result = subprocess.run(
            ["git", "rev-parse", "origin/main"],
            cwd=str(repo),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception as e:
        log.warning("git remote SHA lookup failed", error=str(e))
        return None


def _load_stored_sha() -> str | None:
    if _STATE_FILE.exists():
        return _STATE_FILE.read_text(encoding="utf-8").strip() or None
    return None


def _save_sha(sha: str) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STATE_FILE.with_suffix(".tmp")
    tmp.write_text(sha + "\n", encoding="utf-8")
    tmp.rename(_STATE_FILE)


def _deploy(repo: Path, sha: str) -> bool:
    """Pull latest main and run make restart-all.  Returns True on success."""
    log.info("deploying", sha=sha[:12], repo=str(repo))
    ts = datetime.now(UTC).isoformat()

    try:
        subprocess.run(
            ["git", "pull", "origin", "main", "--ff-only"],
            cwd=str(repo),
            check=True,
            capture_output=True,
            timeout=120,
        )
    except subprocess.CalledProcessError as e:
        log.error("git pull failed", sha=sha[:12], stderr=e.stderr.decode() if e.stderr else "")
        return False

    try:
        subprocess.run(
            ["make", "restart-all"],
            cwd=str(repo),
            check=True,
            timeout=120,
        )
        log.info("deploy complete", sha=sha[:12], ts=ts)
        return True
    except subprocess.CalledProcessError as e:
        log.error("make restart-all failed", sha=sha[:12], returncode=e.returncode)
        return False


# ---------------------------------------------------------------------------
# RedeployWatcher
# ---------------------------------------------------------------------------

class RedeployWatcher:
    """Polls git for new commits on origin/main and redeploys on change."""

    def __init__(
        self,
        *,
        poll_interval_s: float | None = None,
        state_file: Path | None = None,
    ) -> None:
        self._poll_interval_s = poll_interval_s or float(
            os.environ.get("REDEPLOY_POLL_INTERVAL_SECONDS", _DEFAULT_POLL_INTERVAL_S)
        )
        if state_file:
            global _STATE_FILE
            _STATE_FILE = state_file
        self._running = True
        self._repo = _repo_path()

    def stop(self) -> None:
        self._running = False

    async def start(self) -> None:
        log.info(
            "RedeployWatcher starting",
            repo=str(self._repo),
            poll_interval=self._poll_interval_s,
            state_file=str(_STATE_FILE),
        )

        # Eager deploy on startup
        stored_sha = _load_stored_sha()
        current_sha = _git_remote_sha(self._repo)
        if current_sha and current_sha != stored_sha:
            log.info("eager deploy on startup", old_sha=stored_sha, new_sha=current_sha[:12])
            if _deploy(self._repo, current_sha):
                _save_sha(current_sha)
        elif current_sha:
            log.info("up to date on startup", sha=current_sha[:12])

        while self._running:
            await asyncio.sleep(self._poll_interval_s)
            if not self._running:
                break
            await self._check_and_deploy()

    async def _check_and_deploy(self) -> None:
        loop = asyncio.get_event_loop()
        current_sha = await loop.run_in_executor(None, _git_remote_sha, self._repo)
        if not current_sha:
            return

        stored_sha = _load_stored_sha()
        if current_sha == stored_sha:
            return

        log.info("new SHA on origin/main", old=stored_sha, new=current_sha[:12])
        success = await loop.run_in_executor(None, _deploy, self._repo, current_sha)
        if success:
            _save_sha(current_sha)


def install_signal_handlers(watcher: RedeployWatcher) -> None:
    """Install SIGTERM / SIGINT handlers that call watcher.stop()."""

    def _handle(sig, _frame):
        log.info("signal received, stopping", signal=sig)
        watcher.stop()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
