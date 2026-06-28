"""Quill Dev-Chat Worker — Cloud Run service.
Receives tasks from Cloud Tasks, calls ADK coordinator, updates task status."""
import os, json
import httpx
from fastapi import FastAPI, Request, HTTPException

app = FastAPI(title="Quill Dev-Chat Worker")

QUILL_BACKEND = os.environ.get("QUILL_BACKEND_URL", "https://quill-agents-qdur2ylusq-uc.a.run.app")
ADK_URL = os.environ.get("ADK_AGENTS_URL", "https://quill-agents-894031978246.us-central1.run.app")

@app.get("/health")
def health():
    return {"status": "ok", "service": "quill-dev-chat-worker"}

@app.post("/process")
async def process_task(request: Request):
    body = await request.json()
    task_id = body.get("task_id")
    thread_id = body.get("thread_id")
    user_message = body.get("message", "")
    worker_token = body.get("worker_token", "")

    if not task_id:
        raise HTTPException(400, "Missing task_id")

    headers = {"X-Worker-Token": worker_token}

    # Mark running
    async with httpx.AsyncClient(timeout=10) as c:
        await c.post(f"{QUILL_BACKEND}/v1/dev-chat/worker/tasks/{task_id}/running",
                     json={"progress": "Processing with AI agents..."}, headers=headers)

    try:
        async with httpx.AsyncClient(timeout=120) as c:
            resp = await c.post(f"{ADK_URL}/invoke",
                json={"agent": "quill_coordinator", "message": user_message,
                      "session_id": f"dev-chat-{thread_id}"})
            if resp.status_code == 200:
                response_text = resp.json().get("response", "Done.")
            else:
                response_text = f"Agent returned {resp.status_code}: {resp.text[:200]}"

        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"{QUILL_BACKEND}/v1/dev-chat/worker/tasks/{task_id}/complete",
                         json={"result_markdown": response_text}, headers=headers)
    except Exception as e:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"{QUILL_BACKEND}/v1/dev-chat/worker/tasks/{task_id}/complete",
                         json={"result_markdown": f"Error: {str(e)[:300]}"}, headers=headers)

    return {"ok": True}
