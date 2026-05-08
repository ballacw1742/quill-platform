"""Real-time approval feed: WebSocket primary, SSE fallback."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from app.services.realtime import broadcaster

router = APIRouter(tags=["realtime"])


@router.websocket("/ws/approvals")
async def ws_approvals(ws: WebSocket) -> None:
    await ws.accept()
    q = await broadcaster.subscribe()
    try:
        await ws.send_json({"type": "hello", "channel": "approvals"})
        while True:
            msg = await q.get()
            await ws.send_text(msg)
    except WebSocketDisconnect:
        pass
    finally:
        await broadcaster.unsubscribe(q)


@router.get("/sse/approvals")
async def sse_approvals() -> StreamingResponse:
    q = await broadcaster.subscribe()

    async def event_stream():
        try:
            yield 'event: hello\ndata: {"channel":"approvals"}\n\n'
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"event: approval\ndata: {msg}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            await broadcaster.unsubscribe(q)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
