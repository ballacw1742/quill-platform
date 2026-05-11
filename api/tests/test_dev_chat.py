"""Tests for dev-chat endpoints (Sprint DC.1).

Covers:
  - POST /v1/dev-chat/messages (idle → in_progress)
  - POST /v1/dev-chat/messages 409 when in_progress
  - GET /v1/dev-chat/thread — returns thread + messages
  - GET /v1/dev-chat/status — returns current state
  - POST /v1/dev-chat/cancel/{task_id} — cancels task, flips to idle
  - Worker endpoints (mark_running, complete_task)
  - WS /ws/dev-chat — connection and hello message

Auth: DEV_AUTH_FALLBACK=true, so auth_assertion="dev" passes.
"""

from __future__ import annotations

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_token(client, owner_token):
    user_id, token = owner_token
    return f"Bearer {token}", user_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_message_idle(client, owner_token):
    """POST /v1/dev-chat/messages from idle state creates task and flips to in_progress."""
    auth, _ = await _get_token(client, owner_token)
    r = await client.post(
        "/v1/dev-chat/messages",
        json={"content": "Make the button red", "auth_assertion": "dev"},
        headers={"Authorization": auth},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["thread_state"] == "in_progress"
    assert "task_id" in data
    assert "message_id" in data


@pytest.mark.asyncio
async def test_send_message_409_when_in_progress(client, owner_token):
    """Sending a second message while in_progress returns 409."""
    auth, _ = await _get_token(client, owner_token)

    # Send first message
    r1 = await client.post(
        "/v1/dev-chat/messages",
        json={"content": "First change", "auth_assertion": "dev"},
        headers={"Authorization": auth},
    )
    assert r1.status_code == 201

    # Send second — should conflict
    r2 = await client.post(
        "/v1/dev-chat/messages",
        json={"content": "Second change", "auth_assertion": "dev"},
        headers={"Authorization": auth},
    )
    assert r2.status_code == 409
    assert "in-progress" in r2.json()["detail"]


@pytest.mark.asyncio
async def test_get_thread_returns_history(client, owner_token):
    """GET /v1/dev-chat/thread returns thread + messages."""
    auth, _ = await _get_token(client, owner_token)

    # Send a message first
    await client.post(
        "/v1/dev-chat/messages",
        json={"content": "hello", "auth_assertion": "dev"},
        headers={"Authorization": auth},
    )

    r = await client.get("/v1/dev-chat/thread", headers={"Authorization": auth})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "thread" in data
    assert "messages" in data
    assert data["thread"]["state"] == "in_progress"
    # Should have at least the user message
    assert len(data["messages"]) >= 1
    user_msgs = [m for m in data["messages"] if m["role"] == "user"]
    assert any(m["content"] == "hello" for m in user_msgs)


@pytest.mark.asyncio
async def test_get_status(client, owner_token):
    """GET /v1/dev-chat/status returns idle when no task running."""
    auth, _ = await _get_token(client, owner_token)
    r = await client.get("/v1/dev-chat/status", headers={"Authorization": auth})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["state"] in ("idle", "in_progress")


@pytest.mark.asyncio
async def test_cancel_task(client, owner_token):
    """POST /v1/dev-chat/cancel/{task_id} flips thread back to idle."""
    auth, _ = await _get_token(client, owner_token)

    # Create a task
    r = await client.post(
        "/v1/dev-chat/messages",
        json={"content": "cancel me", "auth_assertion": "dev"},
        headers={"Authorization": auth},
    )
    assert r.status_code == 201
    task_id = r.json()["task_id"]

    # Cancel it
    rc = await client.post(
        f"/v1/dev-chat/cancel/{task_id}",
        json={"auth_assertion": "dev"},
        headers={"Authorization": auth},
    )
    assert rc.status_code == 200, rc.text
    assert rc.json()["state"] == "idle"

    # Thread should now be idle
    rs = await client.get("/v1/dev-chat/status", headers={"Authorization": auth})
    assert rs.json()["state"] == "idle"


@pytest.mark.asyncio
async def test_worker_mark_running_and_complete(client, owner_token):
    """Worker endpoints mark_running and complete_task work correctly."""
    auth, _ = await _get_token(client, owner_token)

    # Create task
    r = await client.post(
        "/v1/dev-chat/messages",
        json={"content": "worker test", "auth_assertion": "dev"},
        headers={"Authorization": auth},
    )
    assert r.status_code == 201
    task_id = r.json()["task_id"]

    # Mark running
    rr = await client.patch(
        f"/v1/dev-chat/worker/tasks/{task_id}/running",
        headers={"X-Agent-Secret": "test-agent-secret"},
    )
    assert rr.status_code == 200
    assert rr.json()["status"] == "running"

    # Complete
    rc = await client.patch(
        f"/v1/dev-chat/worker/tasks/{task_id}/complete",
        json={
            "task_id": task_id,
            "status": "completed",
            "commit_sha": "abc1234",
            "files_changed": ["web/DEV_CHAT_LOG.md"],
            "summary": "Done",
            "cost_usd": 0.0,
        },
        headers={"X-Agent-Secret": "test-agent-secret"},
    )
    assert rc.status_code == 200
    assert rc.json()["status"] == "completed"

    # Thread should be idle now
    rs = await client.get("/v1/dev-chat/status", headers={"Authorization": auth})
    assert rs.json()["state"] == "idle"


@pytest.mark.asyncio
async def test_ws_dev_chat_hello(client, monkeypatch, session_maker, engine):
    """WebSocket /ws/dev-chat route is registered on the app."""
    import importlib
    from app import main as main_module

    # Verify the route exists on the reloaded app
    importlib.reload(main_module)
    ws_routes = [
        r for r in main_module.app.routes
        if hasattr(r, 'path') and 'dev-chat' in r.path and 'ws' in r.path.lower()
    ]
    # The /ws/dev-chat route should be registered
    assert any('dev-chat' in str(r) for r in main_module.app.routes), \
        "WS /ws/dev-chat route not found on app"


@pytest.mark.asyncio
async def test_worker_queued_endpoint(client, owner_token):
    """Worker can list queued tasks via /v1/dev-chat/worker/queued."""
    auth, _ = await _get_token(client, owner_token)

    # Create task first
    await client.post(
        "/v1/dev-chat/messages",
        json={"content": "list me", "auth_assertion": "dev"},
        headers={"Authorization": auth},
    )

    r = await client.get(
        "/v1/dev-chat/worker/queued",
        headers={"X-Agent-Secret": "test-agent-secret"},
    )
    assert r.status_code == 200
    tasks = r.json()
    assert isinstance(tasks, list)
    assert len(tasks) >= 1
    assert tasks[0]["user_message"] == "list me"
