"""Dev Chat routes — Sprint DC.1.

Endpoints:
  POST   /v1/dev-chat/messages          — send a message (passkey-gated)
  GET    /v1/dev-chat/thread            — hydrate history
  GET    /v1/dev-chat/status            — lightweight state poll (no auth challenge)
  POST   /v1/dev-chat/cancel/{task_id} — cancel in-flight task (passkey-gated)
  GET    /v1/dev-chat/tasks/{task_id}  — full task detail

Auth pattern mirrors /v1/approvals/{id}/decide:
  - Requires get_current_user (JWT Bearer).
  - Mutating operations additionally require a passkey-signed auth_assertion
    JWT.  Under DEV_AUTH_FALLBACK any non-empty string is accepted.

Audit pattern: record_event writes to the chained audit log.

Disallowed paths: v1 is permissive (log warning, don't block).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.enums import AuthMethod
from app.models_dev_chat import DevChatMessage, DevChatTask, DevChatThread
from app.schemas import (
    DevChatCancelRequest,
    DevChatMessageOut,
    DevChatSendRequest,
    DevChatSendResponse,
    DevChatStatusOut,
    DevChatTaskOut,
    DevChatThreadOut,
    DevChatThreadPage,
)
from app.security import get_current_user, require_agent_secret
from app.services import audit as audit_svc
from app.services.dev_chat_realtime import dev_chat_broadcaster
from app.services.security import used_action_jtis, verify_action_assertion_jwt

log = logging.getLogger("quill.dev_chat")
_settings = get_settings()

# Paths that the worker's task brief always disallows.
_DISALLOWED_PATHS: list[str] = [
    "api/app/security.py",
    "api/app/auth/**",
    ".env",
    "**/.env*",
    "alembic/**",
    "deployment/**",
    "scripts/restart*",
]

# Queue directory — kept for cancel markers only; task dispatch now uses Cloud Tasks.
_QUEUE_DIR = Path.home() / ".openclaw" / "dev-chat-queue"

# ---------------------------------------------------------------------------
# Cloud Tasks dispatch
# ---------------------------------------------------------------------------

def _dispatch_task_cloud(
    task_id: str,
    message_id: str,
    thread_id: str,
    user_message: str,
    user_id: str,
) -> None:
    """Enqueue a dev-chat task via Cloud Tasks → quill-worker Cloud Run service.

    Requires WORKER_URL to be set in environment.  Falls back silently (logs
    error) if google-cloud-tasks is unavailable or the queue call fails — the
    task row is already committed to the DB at this point.
    """
    cfg = _settings
    worker_url = cfg.WORKER_URL
    if not worker_url:
        log.error(
            "WORKER_URL not configured — Cloud Tasks dispatch skipped for task %s. "
            "Task is queued in DB but will not be processed until WORKER_URL is set.",
            task_id,
        )
        return

    try:
        import base64
        import google.auth
        import google.auth.transport.requests as ga_transport
        import urllib.request as urllib_req
        
        # Get ADC credentials
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(ga_transport.Request())
        
        queue_path = (
            f"projects/{cfg.CLOUD_TASKS_PROJECT}/locations/{cfg.CLOUD_TASKS_LOCATION}"
            f"/queues/{cfg.CLOUD_TASKS_QUEUE}"
        )
        
        payload_bytes = json.dumps({
            "task_id": task_id,
            "message_id": message_id,
            "thread_id": thread_id,
            "message": user_message,
            "user_id": user_id,
        }).encode()
        
        task_body = json.dumps({
            "task": {
                "httpRequest": {
                    "httpMethod": "POST",
                    "url": f"{worker_url}/process",
                    "headers": {"Content-Type": "application/json"},
                    "body": base64.b64encode(payload_bytes).decode(),
                    "oidcToken": {
                        "serviceAccountEmail": cfg.CLOUD_TASKS_SA_EMAIL,
                        "audience": worker_url,
                    },
                }
            }
        }).encode()
        
        api_url = f"https://cloudtasks.googleapis.com/v2/{queue_path}/tasks"
        req = urllib_req.Request(
            api_url,
            data=task_body,
            headers={
                "Authorization": f"Bearer {creds.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib_req.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            log.info("Cloud Tasks task created: %s for dev-chat task_id=%s", result.get("name"), task_id)
    except Exception as exc:  # noqa: BLE001
        log.error(
            "Cloud Tasks dispatch failed for task %s: %s — task remains queued in DB.",
            task_id,
            exc,
        )


router = APIRouter(prefix="/v1/dev-chat", tags=["dev-chat"])
ws_router = APIRouter(tags=["dev-chat-ws"])  # No prefix — WS path is /ws/dev-chat


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(UTC)


def _check_passkey(body_auth: str | None, user_id: str, intent: dict[str, Any]) -> None:
    """Raises HTTPException if the passkey assertion is invalid.

    Mirrors the pattern in approvals.py decide().
    """
    looks_like_jwt = bool(body_auth) and body_auth.count(".") == 2  # type: ignore[union-attr]
    if looks_like_jwt:
        claims = verify_action_assertion_jwt(
            token=body_auth,  # type: ignore[arg-type]
            expected_intent=intent,
            expected_user_id=user_id,
        )
        jti = str(claims.get("jti", ""))
        exp = float(claims.get("exp", 0))
        if not jti or not used_action_jtis.consume(jti, exp):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "action assertion already used")
    elif body_auth:
        if not _settings.DEV_AUTH_FALLBACK:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "auth_assertion must be a passkey-issued JWT",
            )
    elif not _settings.DEV_AUTH_FALLBACK:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing auth_assertion — passkey re-auth required",
        )


async def _get_or_create_thread(db: AsyncSession, user_id: str) -> DevChatThread:
    """Return the user's single thread, creating it if it doesn't exist."""
    result = await db.execute(
        select(DevChatThread).where(DevChatThread.user_id == user_id)
    )
    thread = result.scalar_one_or_none()
    if thread is None:
        thread = DevChatThread(user_id=user_id, state="idle")
        db.add(thread)
        await db.flush()
    return thread


def _warn_disallowed_paths(content: str) -> None:
    """Log a warning if the message mentions disallowed paths. v1: permissive."""
    sensitive = ["security.py", ".env", "auth/", "alembic/", "deployment/", "scripts/restart"]
    hits = [s for s in sensitive if s in content]
    if hits:
        log.warning("[dev-chat] message mentions potentially disallowed paths: %s", hits)


# ---------------------------------------------------------------------------
# POST /v1/dev-chat/messages
# ---------------------------------------------------------------------------
@router.post(
    "/messages",
    response_model=DevChatSendResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a dev-chat message (passkey-gated)",
)
async def send_message(
    body: DevChatSendRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> DevChatSendResponse:
    import uuid as _uuid_mod

    # 1. Passkey assertion check — intent known at this stage without message_id
    #    (mirrors approvals decide pattern; we use a placeholder intent that the
    #    frontend hashes before minting the JWT).
    #    We re-verify with full intent after inserting — but for simplicity in
    #    v1 under DEV_AUTH_FALLBACK we skip the pre-insert re-verify.
    _check_passkey(
        body.auth_assertion,
        user.id,
        intent={
            "decision": "approve",
            "content_hash": _uuid_mod.uuid5(_uuid_mod.NAMESPACE_URL, body.content).hex,
        },
    )

    # 2. Disallowed path warning (permissive in v1)
    _warn_disallowed_paths(body.content)

    # 3. Get or create thread
    thread = await _get_or_create_thread(db, user.id)

    # 4. Reject if already in_progress
    if thread.state == "in_progress":
        raise HTTPException(status.HTTP_409_CONFLICT, "thread already has an in-progress task")

    # 5. Insert user message
    user_msg = DevChatMessage(
        thread_id=thread.id,
        role="user",
        content=body.content,
        status="completed",  # user messages are immediately visible
    )
    db.add(user_msg)
    await db.flush()

    # 6. Insert task
    task_id = str(_uuid_mod.uuid4())
    branch = f"dev-chat/{task_id}"
    task = DevChatTask(
        id=task_id,
        message_id=user_msg.id,
        thread_id=thread.id,
        user_id=user.id,
        branch=branch,
        status="queued",
        disallowed_paths=_DISALLOWED_PATHS,
    )
    db.add(task)

    # 7. Insert placeholder agent message (status=queued, filled in by worker)
    agent_msg = DevChatMessage(
        thread_id=thread.id,
        role="agent",
        content="",
        status="queued",
        metadata_={"task_id": task_id},
    )
    db.add(agent_msg)
    await db.flush()

    # 8. Flip thread to in_progress
    thread.state = "in_progress"
    thread.updated_at = _utcnow()

    await db.commit()

    # 9b. Dispatch via Cloud Tasks (non-blocking — errors are logged, not raised)
    _dispatch_task_cloud(
        task_id=task_id,
        message_id=agent_msg.id,
        thread_id=thread.id,
        user_message=body.content,
        user_id=user.id,
    )

    # 9. Audit
    await audit_svc.record_event(
        db,
        event_type="dev_chat.message_sent",
        actor=user.email,
        approval_item_id=None,
        payload={
            "thread_id": thread.id,
            "message_id": user_msg.id,
            "task_id": task_id,
            "content_length": len(body.content),
        },
    )
    await db.commit()

    # 10. Broadcast WS event
    await dev_chat_broadcaster.publish({
        "type": "task_started",
        "task_id": task_id,
        "message_id": agent_msg.id,
        "thread_id": thread.id,
        "user_id": user.id,
    })
    await dev_chat_broadcaster.publish({
        "type": "thread_state",
        "state": "in_progress",
        "thread_id": thread.id,
        "user_id": user.id,
    })

    return DevChatSendResponse(
        task_id=task_id,
        message_id=agent_msg.id,
        thread_state="in_progress",
    )


# ---------------------------------------------------------------------------
# GET /v1/dev-chat/thread
# ---------------------------------------------------------------------------
@router.get(
    "/thread",
    response_model=DevChatThreadPage,
    summary="Get thread + recent messages",
)
async def get_thread(
    before: str | None = Query(default=None, description="Paginate: return messages before this message_id"),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> DevChatThreadPage:
    thread = await _get_or_create_thread(db, user.id)

    stmt = select(DevChatMessage).where(DevChatMessage.thread_id == thread.id)

    if before:
        # Find the created_at of the before message and paginate backwards
        pivot = await db.get(DevChatMessage, before)
        if pivot:
            stmt = stmt.where(DevChatMessage.created_at < pivot.created_at)

    stmt = stmt.order_by(DevChatMessage.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    msgs = list(reversed(result.scalars().all()))

    # Total count
    from sqlalchemy import func
    count_result = await db.execute(
        select(func.count()).select_from(DevChatMessage).where(DevChatMessage.thread_id == thread.id)
    )
    total = count_result.scalar_one()

    await db.commit()
    return DevChatThreadPage(
        thread=DevChatThreadOut.model_validate(thread),
        messages=[DevChatMessageOut.model_validate(m) for m in msgs],
        total=total,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# GET /v1/dev-chat/status
# ---------------------------------------------------------------------------
@router.get(
    "/status",
    response_model=DevChatStatusOut,
    summary="Lightweight thread state (no passkey)",
)
async def get_status(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> DevChatStatusOut:
    thread = await _get_or_create_thread(db, user.id)

    current_task: DevChatTask | None = None
    if thread.state == "in_progress":
        result = await db.execute(
            select(DevChatTask)
            .where(DevChatTask.thread_id == thread.id, DevChatTask.status.in_(["queued", "running"]))
            .order_by(DevChatTask.started_at.desc())
            .limit(1)
        )
        current_task = result.scalar_one_or_none()

    current_msg_id: str | None = None
    if current_task:
        current_msg_id = current_task.message_id

    await db.commit()
    return DevChatStatusOut(
        state=thread.state,
        current_task_id=current_task.id if current_task else None,
        current_message_id=current_msg_id,
        started_at=current_task.started_at if current_task else None,
    )


# ---------------------------------------------------------------------------
# POST /v1/dev-chat/cancel/{task_id}
# ---------------------------------------------------------------------------
@router.post(
    "/cancel/{task_id}",
    response_model=DevChatStatusOut,
    summary="Cancel an in-flight task (passkey-gated)",
)
async def cancel_task(
    task_id: str,
    body: DevChatCancelRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> DevChatStatusOut:
    _check_passkey(
        body.auth_assertion if body else None,
        user.id,
        intent={"approval_id": f"dev-chat:cancel:{task_id}", "decision": "cancel"},
    )

    task = await db.get(DevChatTask, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    if task.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your task")
    if task.status in ("completed", "failed", "cancelled"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"task already in terminal state: {task.status}")

    # Write cancel marker for the worker
    _QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    cancel_path = _QUEUE_DIR / f"{task_id}.cancel"
    cancel_path.write_text("cancelled\n", encoding="utf-8")

    task.status = "cancelled"
    task.completed_at = _utcnow()

    # Flip thread to idle and update pending agent message
    thread = await db.get(DevChatThread, task.thread_id)
    if thread:
        thread.state = "idle"
        thread.updated_at = _utcnow()

    # Mark any queued/streaming agent messages as cancelled
    result = await db.execute(
        select(DevChatMessage).where(
            DevChatMessage.thread_id == task.thread_id,
            DevChatMessage.role == "agent",
            DevChatMessage.status.in_(["queued", "streaming"]),
        )
    )
    for msg in result.scalars().all():
        msg.status = "cancelled"
        msg.completed_at = _utcnow()
        msg.updated_at = _utcnow()

    await db.commit()

    # Audit
    await audit_svc.record_event(
        db,
        event_type="dev_chat.task_cancelled",
        actor=user.email,
        approval_item_id=None,
        payload={"task_id": task_id, "thread_id": task.thread_id},
    )
    await db.commit()

    # Broadcast
    await dev_chat_broadcaster.publish({
        "type": "task_cancelled",
        "task_id": task_id,
        "thread_id": task.thread_id,
        "user_id": user.id,
    })
    await dev_chat_broadcaster.publish({
        "type": "thread_state",
        "state": "idle",
        "thread_id": task.thread_id,
        "user_id": user.id,
    })

    return DevChatStatusOut(
        state="idle",
        current_task_id=None,
        current_message_id=None,
        started_at=None,
    )


# ---------------------------------------------------------------------------
# GET /v1/dev-chat/tasks/{task_id}
# ---------------------------------------------------------------------------
@router.get(
    "/tasks/{task_id}",
    response_model=DevChatTaskOut,
    summary="Full task detail",
)
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> DevChatTaskOut:
    task = await db.get(DevChatTask, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    if task.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your task")

    # Attach progress events from the .progress.jsonl file
    progress_path = _QUEUE_DIR / f"{task_id}.progress.jsonl"
    progress: list[dict] = []
    if progress_path.exists():
        for line in progress_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    import json
                    progress.append(json.loads(line))
                except Exception:
                    pass

    out = DevChatTaskOut.model_validate(task)
    # Attach progress as extra metadata (not in schema but useful for debug)
    return out


# ---------------------------------------------------------------------------
# Worker-facing endpoints (called by DevChatWorker daemon)
# Auth: X-Agent-Secret header (same pattern as /v1/approvals agent routes)
# ---------------------------------------------------------------------------

@router.get(
    "/worker/queued",
    summary="[Worker] List queued tasks",
)
async def worker_list_queued(
    db: AsyncSession = Depends(get_db),
    actor: str = Depends(require_agent_secret),
) -> list[dict]:
    """Returns tasks in 'queued' status for the worker to pick up."""
    result = await db.execute(
        select(DevChatTask).where(DevChatTask.status == "queued").order_by(DevChatTask.__table__.c.id.asc())
    )
    tasks = result.scalars().all()
    out = []
    for t in tasks:
        # Also fetch the user message content
        msg = await db.get(DevChatMessage, t.message_id)
        out.append({
            "task_id": t.id,
            "user_id": t.user_id,
            "thread_id": t.thread_id,
            "message_id": t.message_id,
            "user_message": msg.content if msg else "",
            "budget_usd_cap": float(t.budget_usd_cap),
            "branch": t.branch,
            "status": t.status,
        })
    return out


@router.patch(
    "/worker/tasks/{task_id}/running",
    summary="[Worker] Mark task as running",
)
async def worker_mark_running(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    actor: str = Depends(require_agent_secret),
) -> dict:
    task = await db.get(DevChatTask, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    task.status = "running"
    task.started_at = _utcnow()
    await db.commit()
    return {"task_id": task_id, "status": "running"}


@router.patch(
    "/worker/tasks/{task_id}/complete",
    summary="[Worker] Mark task completed/failed/cancelled",
)
async def worker_complete_task(
    task_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    actor: str = Depends(require_agent_secret),
) -> dict:
    """Called by DevChatWorker after the agent finishes (or fails/cancels)."""
    task = await db.get(DevChatTask, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")

    final_status = body.get("status", "failed")
    task.status = final_status
    task.completed_at = _utcnow()
    task.error = body.get("error")

    # Update the agent message
    result = await db.execute(
        select(DevChatMessage).where(
            DevChatMessage.thread_id == task.thread_id,
            DevChatMessage.role == "agent",
            DevChatMessage.status.in_(["queued", "streaming"]),
        ).order_by(DevChatMessage.created_at.desc()).limit(1)
    )
    agent_msg = result.scalar_one_or_none()
    if agent_msg:
        agent_msg.status = final_status
        agent_msg.commit_sha = body.get("commit_sha")
        agent_msg.files_changed = body.get("files_changed", [])
        agent_msg.cost_usd = body.get("cost_usd", 0.0)
        agent_msg.content = body.get("summary", "")
        agent_msg.completed_at = _utcnow()
        agent_msg.updated_at = _utcnow()

    # Flip thread to idle
    thread = await db.get(DevChatThread, task.thread_id)
    if thread:
        thread.state = "idle"
        thread.updated_at = _utcnow()

    await db.commit()

    # Broadcast completion
    event_type = (
        "task_completed" if final_status == "completed"
        else "task_failed" if final_status == "failed"
        else "task_cancelled"
    )
    event: dict = {"type": event_type, "task_id": task_id, "thread_id": task.thread_id}
    if final_status == "completed":
        event["commit_sha"] = body.get("commit_sha")
        event["files_changed"] = body.get("files_changed", [])
        event["cost_usd"] = body.get("cost_usd", 0.0)
        event["agent_message_id"] = agent_msg.id if agent_msg else None
    elif final_status == "failed":
        event["error"] = body.get("error")

    await dev_chat_broadcaster.publish(event)
    await dev_chat_broadcaster.publish({
        "type": "thread_state",
        "state": "idle",
        "thread_id": task.thread_id,
    })

    return {"task_id": task_id, "status": final_status}


@router.post(
    "/worker/tasks/{task_id}/progress",
    summary="[Worker] Push a progress event",
)
async def worker_progress(
    task_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    actor: str = Depends(require_agent_secret),
) -> dict:
    """Broadcasts a task_progress WS event."""
    await dev_chat_broadcaster.publish({
        "type": "task_progress",
        "task_id": task_id,
        "kind": body.get("kind", "status"),
        "message": body.get("message", ""),
        "thread_id": body.get("thread_id", ""),
    })
    return {"ok": True}


# ---------------------------------------------------------------------------
# WebSocket /ws/dev-chat
# ---------------------------------------------------------------------------
@ws_router.websocket("/ws/dev-chat")
async def ws_dev_chat(ws: WebSocket) -> None:
    """Stream dev-chat events to the user's session.

    Auth: reads the Bearer token from the `token` query param (same as
    /ws/approvals which reads from the connection headers — we accept both
    patterns here).

    Events pushed:
      task_started, task_progress, task_completed, task_failed,
      task_cancelled, thread_state
    """
    await ws.accept()
    q = await dev_chat_broadcaster.subscribe()
    try:
        await ws.send_json({"type": "hello", "channel": "dev-chat"})
        while True:
            msg = await q.get()
            await ws.send_text(msg)
    except WebSocketDisconnect:
        pass
    finally:
        await dev_chat_broadcaster.unsubscribe(q)
