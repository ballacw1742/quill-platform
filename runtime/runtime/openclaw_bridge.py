"""OpenClaw bridge — translates dev-chat queue tasks into real coding-agent runs.

Architecture:

  /v1/dev-chat/messages POST
        ↓
  DevChatWorker (production mode)
        ↓ writes  ~/.openclaw/dev-chat-queue/<task_id>.task.json
        ↓ tails    ~/.openclaw/dev-chat-queue/<task_id>.progress.jsonl
        ↓ awaits   ~/.openclaw/dev-chat-queue/<task_id>.result.json
        ↓
  OpenClawBridge (THIS DAEMON)
        ↓ polls queue dir for *.task.json
        ↓ builds a constrained coding-agent prompt
        ↓ shells out: openclaw agent --json --message <prompt> --thinking medium
        ↓ inspects git for new commit on origin/main
        ↓ writes <task_id>.result.json
  → DevChatWorker reads .result.json → updates DB + WebSocket → UI

Why a separate daemon (not inside the FastAPI app):
  - Keeps the bridge process boundary cleanly separable for security review.
  - Lets us run it under a different env (e.g. with different API keys) if
    we later route to a non-default agent or model.
  - The OpenClaw `agent` command can take a long time; we don't want it
    holding a FastAPI worker.

Safety:
  - Each task has a budget cap (informational in v1; openclaw agent doesn't
    enforce $ caps yet — we just abort if wall-clock exceeds 30 min).
  - Disallowed paths are enforced post-hoc: after the agent finishes, we
    inspect the diff and refuse to publish results that touched a disallowed
    file. We reset HEAD if a violation is detected.
  - All bridge actions are audited via stdout structured logging that the
    DevChatWorker captures into the audit log.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Default queue directory (matches the worker side).
DEFAULT_QUEUE_DIR = Path.home() / ".openclaw" / "dev-chat-queue"

# Hard wall-clock cap per task. OpenClaw `agent` invocation defaults to 600s,
# but we allow a longer ceiling for non-trivial multi-step edits.
DEFAULT_TASK_TIMEOUT_S = 30 * 60

# Default poll interval for new task files.
DEFAULT_POLL_INTERVAL_S = 2.0


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _log(kind: str, **fields: Any) -> None:
    """Structured stdout log. JSON line, one per event."""
    fields["ts"] = _iso_now()
    fields["kind"] = kind
    print(json.dumps(fields, default=str), flush=True)


@dataclass
class TaskFile:
    task_id: str
    user_id: str
    user_message: str
    branch: str
    budget_usd_cap: float
    disallowed_paths: list[str]
    repo_path: Path
    thread_id: str
    requested_at: str

    @classmethod
    def from_path(cls, path: Path) -> TaskFile | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            _log("bridge.task_parse_failed", path=str(path), err=str(exc))
            return None
        ctx = data.get("context", {})
        repo = Path(ctx.get("repo_path") or "")
        if not repo.exists():
            _log("bridge.task_invalid_repo", task_id=data.get("task_id"), repo=str(repo))
            return None
        return cls(
            task_id=str(data["task_id"]),
            user_id=str(data.get("user_id") or ""),
            user_message=str(data["user_message"]),
            branch=str(data.get("branch") or f"dev-chat/{data['task_id']}"),
            budget_usd_cap=float(data.get("budget_usd_cap") or 2.0),
            disallowed_paths=list(data.get("disallowed_paths") or []),
            repo_path=repo,
            thread_id=str(ctx.get("thread_id") or ""),
            requested_at=str(data.get("requested_at") or _iso_now()),
        )


def _git(repo: Path, *args: str, capture: bool = True) -> str:
    """Run git in the repo. Returns stdout. Raises on non-zero exit."""
    out = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=capture,
        text=True,
    )
    return (out.stdout or "").strip()


def _head_sha(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")


def _diff_paths(repo: Path, from_sha: str, to_sha: str) -> list[str]:
    out = _git(repo, "diff", "--name-only", f"{from_sha}..{to_sha}")
    return [p for p in out.splitlines() if p.strip()]


def _path_is_disallowed(path: str, patterns: list[str]) -> bool:
    """fnmatch-style match against any disallowed pattern."""
    for p in patterns:
        if fnmatch.fnmatch(path, p):
            return True
    return False


def _build_agent_prompt(task: TaskFile) -> str:
    """Craft the prompt that goes to `openclaw agent`. Constrained, single-turn."""
    disallowed_lines = "\n".join(f"  - {p}" for p in task.disallowed_paths)
    return f"""You are servicing a dev-chat code-change request from Charles via Quill's in-app /dev-chat module.

# User request (verbatim)

{task.user_message}

# Repository

Working directory: {task.repo_path}

# Hard rules

- Make the smallest reasonable code change to satisfy the request.
- Do not touch any of these paths under any circumstance:
{disallowed_lines}
- Run no migrations, no destructive commands, no service restarts. The deploy watcher daemon handles redeploy automatically once you push.
- Stage and commit ALL your changes with a clear commit message that includes the user's verbatim request on the second line.
- Push to origin/main directly (the deploy watcher will pick up the new SHA).
- If the request is ambiguous, dangerous, or out of scope, do NOT make any code change. Instead commit a small text-only note to a file named DEV_CHAT_LOG.md at the repo root explaining what you did NOT do and why, with the user's request on the second line of the commit message.
- If you encounter a problem you can't resolve, do the same: write an explanation to DEV_CHAT_LOG.md and commit it.
- This is a single-turn task. Do not ask follow-up questions. Make the best decision and ship it.

# Conversational requests

If the user is clearly asking a question ("what can you do", "how does X work", "why did Y happen") rather than requesting a code change:
- Answer the question directly and concisely in your final assistant message
- The user sees your final assistant text rendered in their chat — write it like a normal chat reply, not a status update
- Still commit a single-line note to DEV_CHAT_LOG.md so there's a paper trail (commit message: `dev-chat(qa): <topic>` and body = user's question verbatim + Task-Id)
- Keep the chat reply itself focused: lead with the answer, bullets over walls of text, no JSON dumps, no "Let me scan..." preludes — just the answer.

# Constraints

- Budget: ~${task.budget_usd_cap:.2f} per task. Keep your edits proportional.
- All existing tests in the repo must still pass — run `cd web && npm test -- --run` (UI) and the relevant pytest suites for any backend edits. Skip running tests only if the change is purely cosmetic CSS.
- If the task is genuinely large (multi-hour), still do the minimum useful slice and commit it; do not refuse to act.

# Required commit format

```
dev-chat(<short scope>): <one-line summary>

<user message verbatim>

Task-Id: {task.task_id}
```

# When you are done

End your turn with a single line: `DEV-CHAT-DONE` so the bridge can detect completion.

Begin now.
"""


def _run_openclaw_agent(
    *,
    task: TaskFile,
    timeout_s: int,
    progress_path: Path,
) -> tuple[bool, str]:
    """Shell out to openclaw agent. Returns (succeeded, summary_or_error)."""
    prompt = _build_agent_prompt(task)
    # Target the main agent context (Axe). Without --agent the CLI requires
    # --to or --session-id; we want a fresh, isolated turn each time.
    agent_id = os.environ.get("DEV_CHAT_BRIDGE_AGENT_ID", "main")
    cmd = [
        "openclaw",
        "agent",
        "--agent",
        agent_id,
        "--json",
        "--thinking",
        "medium",
        "--timeout",
        str(timeout_s),
        "--message",
        prompt,
    ]
    _log("bridge.openclaw_invoke", task_id=task.task_id, cmd=" ".join(shlex.quote(c) for c in cmd[:6]) + " <prompt>")
    _append_progress(progress_path, "status", "Invoking openclaw agent…")

    try:
        proc = subprocess.run(
            cmd,
            cwd=task.repo_path,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return False, f"openclaw agent timed out after {timeout_s}s"
    except FileNotFoundError:
        return False, "openclaw CLI not found on PATH"

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:2000]
        return False, f"openclaw agent exit={proc.returncode}: {err}"

    # The agent emits a JSON envelope; extract just the assistant's visible
    # reply for display. Never truncate before parsing or the JSON breaks.
    stdout_raw = (proc.stdout or "").strip()
    summary = _extract_visible_text(stdout_raw)
    return True, summary


def _extract_visible_text(stdout_raw: str) -> str:
    """Pull the assistant's human-readable reply out of openclaw's JSON envelope.

    The envelope can be nested (e.g. `{ result: { run: { finalAssistantVisibleText } } }`)
    so we walk the structure recursively looking for the canonical key. Fall
    back to other common shapes and finally to a clamped slice of stdout.
    """
    if not stdout_raw:
        return ""
    try:
        parsed = json.loads(stdout_raw)
    except Exception:
        # Not JSON — just clamp the raw text.
        return stdout_raw[-1500:]

    candidate_keys = (
        "finalAssistantVisibleText",
        "finalAssistantRawText",
        "assistantVisibleText",
        "response",
        "text",
    )

    def _walk(node: Any) -> str | None:
        if isinstance(node, dict):
            for k in candidate_keys:
                v = node.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            for v in node.values():
                found = _walk(v)
                if found:
                    return found
        elif isinstance(node, list):
            for v in node:
                found = _walk(v)
                if found:
                    return found
        return None

    extracted = _walk(parsed)
    if extracted:
        # Strip the trailing DEV-CHAT-DONE marker we ask the agent to emit.
        cleaned = extracted
        for marker in ("DEV-CHAT-DONE", "DEV_CHAT_DONE"):
            idx = cleaned.find(marker)
            if idx != -1:
                cleaned = cleaned[:idx].rstrip()
        return cleaned[-3000:]

    # No recognizable text field — give up gracefully.
    return "(agent finished but produced no visible text)"


def _append_progress(progress_path: Path, kind: str, message: str) -> None:
    """Append a progress line that DevChatWorker tails into the WS stream."""
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"ts": _iso_now(), "kind": kind, "message": message})
    with progress_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _write_result(queue_dir: Path, task_id: str, payload: dict[str, Any]) -> None:
    out = queue_dir / f"{task_id}.result.json"
    # Atomic write
    tmp = out.with_suffix(".result.json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(out)


def _check_cancelled(queue_dir: Path, task_id: str) -> bool:
    return (queue_dir / f"{task_id}.cancel").exists()


def _handle_task(*, task: TaskFile, queue_dir: Path, timeout_s: int) -> None:
    progress_path = queue_dir / f"{task.task_id}.progress.jsonl"
    result_path = queue_dir / f"{task.task_id}.result.json"
    task_path = queue_dir / f"{task.task_id}.task.json"

    _log("bridge.task_pickup", task_id=task.task_id, branch=task.branch)
    _append_progress(progress_path, "status", "Bridge picked up task")

    start_sha = _head_sha(task.repo_path)
    _append_progress(progress_path, "status", f"Starting from SHA {start_sha[:8]}")

    if _check_cancelled(queue_dir, task.task_id):
        _log("bridge.cancelled_before_start", task_id=task.task_id)
        _write_result(
            queue_dir,
            task.task_id,
            {
                "task_id": task.task_id,
                "status": "cancelled",
                "commit_sha": None,
                "branch": task.branch,
                "merged_to_main": False,
                "files_changed": [],
                "summary": "Cancelled before agent invocation",
                "error": None,
                "cost_usd": 0.0,
                "completed_at": _iso_now(),
            },
        )
        _archive_task_file(task_path)
        return

    started_at = time.time()
    ok, summary_or_err = _run_openclaw_agent(
        task=task,
        timeout_s=timeout_s,
        progress_path=progress_path,
    )
    elapsed = time.time() - started_at
    _log("bridge.openclaw_done", task_id=task.task_id, ok=ok, elapsed_s=round(elapsed, 1))

    if not ok:
        _write_result(
            queue_dir,
            task.task_id,
            {
                "task_id": task.task_id,
                "status": "failed",
                "commit_sha": None,
                "branch": task.branch,
                "merged_to_main": False,
                "files_changed": [],
                "summary": "",
                "error": summary_or_err,
                "cost_usd": 0.0,
                "completed_at": _iso_now(),
            },
        )
        _append_progress(progress_path, "error", summary_or_err[:300])
        _archive_task_file(task_path)
        return

    # Pull latest origin/main into local main (the agent may have pushed).
    try:
        _git(task.repo_path, "fetch", "origin", "main")
        # If we're on main, fast-forward; if we're on another branch, leave alone.
        cur_branch = _git(task.repo_path, "rev-parse", "--abbrev-ref", "HEAD")
        if cur_branch == "main":
            _git(task.repo_path, "merge", "--ff-only", "origin/main")
    except subprocess.CalledProcessError as exc:
        _log("bridge.fetch_warning", task_id=task.task_id, err=str(exc))

    end_sha = _head_sha(task.repo_path)
    files_changed: list[str] = []
    commit_sha: str | None = None
    if end_sha != start_sha:
        files_changed = _diff_paths(task.repo_path, start_sha, end_sha)
        commit_sha = end_sha
    else:
        # Maybe origin moved but local main didn't fast-forward (we're not on main).
        try:
            origin_main = _git(task.repo_path, "rev-parse", "origin/main")
            if origin_main != start_sha:
                files_changed = _diff_paths(task.repo_path, start_sha, origin_main)
                commit_sha = origin_main
                end_sha = origin_main
        except subprocess.CalledProcessError:
            pass

    # Disallowed-paths enforcement (post-hoc).
    violations = [p for p in files_changed if _path_is_disallowed(p, task.disallowed_paths)]
    if violations and commit_sha:
        _log("bridge.disallowed_violation", task_id=task.task_id, violations=violations)
        # Revert the offending commit. We hard-reset origin/main back to start_sha.
        try:
            _git(task.repo_path, "push", "origin", f"+{start_sha}:main")
            _git(task.repo_path, "fetch", "origin", "main")
            cur_branch = _git(task.repo_path, "rev-parse", "--abbrev-ref", "HEAD")
            if cur_branch == "main":
                _git(task.repo_path, "reset", "--hard", "origin/main")
        except subprocess.CalledProcessError as exc:
            _log("bridge.revert_failed", task_id=task.task_id, err=str(exc))
        _write_result(
            queue_dir,
            task.task_id,
            {
                "task_id": task.task_id,
                "status": "failed",
                "commit_sha": None,
                "branch": task.branch,
                "merged_to_main": False,
                "files_changed": files_changed,
                "summary": summary_or_err,
                "error": (
                    "Refused to publish: agent modified disallowed paths "
                    f"({', '.join(violations[:5])}). Repository reset to {start_sha[:8]}."
                ),
                "cost_usd": 0.0,
                "completed_at": _iso_now(),
            },
        )
        _archive_task_file(task_path)
        return

    # Detect cancellation that arrived during the run.
    if _check_cancelled(queue_dir, task.task_id) and not commit_sha:
        _write_result(
            queue_dir,
            task.task_id,
            {
                "task_id": task.task_id,
                "status": "cancelled",
                "commit_sha": None,
                "branch": task.branch,
                "merged_to_main": False,
                "files_changed": [],
                "summary": summary_or_err,
                "error": None,
                "cost_usd": 0.0,
                "completed_at": _iso_now(),
            },
        )
        _archive_task_file(task_path)
        return

    status = "completed" if commit_sha else "failed"
    error = None if commit_sha else "Agent finished without producing any commit"
    _write_result(
        queue_dir,
        task.task_id,
        {
            "task_id": task.task_id,
            "status": status,
            "commit_sha": commit_sha,
            "branch": task.branch,
            "merged_to_main": bool(commit_sha),
            "files_changed": files_changed,
            "summary": summary_or_err[-1500:],
            "error": error,
            "cost_usd": 0.0,  # openclaw agent doesn't return cost yet
            "completed_at": _iso_now(),
        },
    )
    _append_progress(
        progress_path,
        "status" if commit_sha else "error",
        (
            f"Committed {commit_sha[:8] if commit_sha else '—'}; "
            f"{len(files_changed)} file(s) changed"
            if commit_sha
            else (error or "Agent did not commit")
        ),
    )
    _archive_task_file(task_path)


def _archive_task_file(task_path: Path) -> None:
    """Move <task_id>.task.json → <task_id>.task.json.done so we don't reprocess."""
    if not task_path.exists():
        return
    done = task_path.with_suffix(".json.done")
    try:
        task_path.replace(done)
    except OSError:
        pass


def _scan_once(queue_dir: Path, timeout_s: int) -> int:
    """One scan tick. Returns the number of tasks handled."""
    if not queue_dir.exists():
        return 0
    n = 0
    for path in sorted(queue_dir.glob("*.task.json")):
        # Skip if already processed (a corresponding .result.json exists).
        result = path.with_suffix(".json").with_suffix("").parent / (
            path.stem + ".result.json"
        )
        # ".result.json" path beside .task.json:
        result = queue_dir / (path.stem.replace(".task", "") + ".result.json")
        if result.exists():
            continue
        task = TaskFile.from_path(path)
        if task is None:
            _archive_task_file(path)
            continue
        try:
            _handle_task(task=task, queue_dir=queue_dir, timeout_s=timeout_s)
        except Exception as exc:  # noqa: BLE001
            _log("bridge.handler_unexpected_error", task_id=task.task_id, err=str(exc))
            _write_result(
                queue_dir,
                task.task_id,
                {
                    "task_id": task.task_id,
                    "status": "failed",
                    "commit_sha": None,
                    "branch": task.branch,
                    "merged_to_main": False,
                    "files_changed": [],
                    "summary": "",
                    "error": f"Bridge handler crashed: {exc}",
                    "cost_usd": 0.0,
                    "completed_at": _iso_now(),
                },
            )
        n += 1
    return n


async def main_async(
    *,
    queue_dir: Path = DEFAULT_QUEUE_DIR,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    timeout_s: int = DEFAULT_TASK_TIMEOUT_S,
) -> None:
    queue_dir.mkdir(parents=True, exist_ok=True)
    _log("bridge.start", queue=str(queue_dir), poll=poll_interval_s, timeout_s=timeout_s)
    stop = asyncio.Event()

    def _signal_handler() -> None:
        _log("bridge.signal", msg="shutting down")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    while not stop.is_set():
        try:
            _scan_once(queue_dir, timeout_s)
        except Exception as exc:  # noqa: BLE001
            _log("bridge.scan_error", err=str(exc))
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_interval_s)
        except asyncio.TimeoutError:
            pass
    _log("bridge.stop")


def main() -> int:
    queue_dir = Path(os.environ.get("DEV_CHAT_QUEUE_DIR", str(DEFAULT_QUEUE_DIR)))
    poll = float(os.environ.get("DEV_CHAT_BRIDGE_POLL_S", str(DEFAULT_POLL_INTERVAL_S)))
    timeout = int(os.environ.get("DEV_CHAT_BRIDGE_TIMEOUT_S", str(DEFAULT_TASK_TIMEOUT_S)))
    if shutil.which("openclaw") is None:
        _log("bridge.fatal", err="openclaw CLI not found on PATH")
        return 2
    try:
        asyncio.run(main_async(queue_dir=queue_dir, poll_interval_s=poll, timeout_s=timeout))
        return 0
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
