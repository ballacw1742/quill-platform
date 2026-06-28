"""Quill Dev-Chat Worker — Cloud Run service.
Receives tasks from Cloud Tasks, calls ADK coordinator, updates task status."""
import os, json, re
import httpx
from fastapi import FastAPI, Request, HTTPException

app = FastAPI(title="Quill Dev-Chat Worker")

QUILL_BACKEND = os.environ.get("QUILL_BACKEND_URL", "https://quill-agents-qdur2ylusq-uc.a.run.app")
ADK_URL = os.environ.get("ADK_AGENTS_URL", "https://quill-adk-agents-894031978246.us-central1.run.app")
AGENT_SECRET = os.environ.get("AGENT_SHARED_SECRET", "dev-agent-secret-change-me")

@app.get("/health")
def health():
    return {"status": "ok", "service": "quill-dev-chat-worker"}

@app.post("/process")
async def process_task(request: Request):
    body = await request.json()
    task_id = body.get("task_id")
    thread_id = body.get("thread_id")
    user_message = body.get("message", "")

    if not task_id:
        raise HTTPException(400, "Missing task_id")

    headers = {"X-Agent-Secret": AGENT_SECRET}

    # Mark running
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.patch(f"{QUILL_BACKEND}/v1/dev-chat/worker/tasks/{task_id}/running",
                         json={"progress": "Processing with AI agents..."}, headers=headers)
    except Exception:
        pass  # Don't fail if running update fails

    response_text = "I received your request and am processing it."
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            resp = await c.post(f"{ADK_URL}/invoke",
                json={"agent": "quill_coordinator", "message": user_message,
                      "session_id": f"dev-chat-{thread_id}"})
            if resp.status_code == 200:
                data = resp.json()
                raw = data.get("response", "")
                # Strip markdown code fences
                clean = re.sub(r"^```[a-z]*\n?", "", raw.strip(), flags=re.MULTILINE)
                clean = re.sub(r"```$", "", clean.strip()).strip()
                try:
                    plan = json.loads(clean)
                    response_text = plan.get("direct_response") or plan.get("summary") or raw[:500]
                except Exception:
                    response_text = raw[:500] if raw else "Task processed."
    except Exception as e:
        response_text = f"I encountered an issue processing your request: {str(e)[:200]}"

    # Mark complete
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.patch(f"{QUILL_BACKEND}/v1/dev-chat/worker/tasks/{task_id}/complete",
                         json={"status": "completed", "summary": response_text, "cost_usd": 0.01}, headers=headers)
    except Exception as e:
        pass  # Task already in DB, just log

    return {"ok": True, "response_length": len(response_text)}
