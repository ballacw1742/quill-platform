"""quill-agent-orchestrator — Phase A P0 SPIKE.

Minimal tenant-scoped agent orchestrator loop:
  POST /v1/agents/chat {tenant_id, agent_id, message}
    -> load/create tenant, agent, session + history (Postgres, agentcloud_* tables)
    -> Claude tool loop (Anthropic API direct; Vertex gap documented in SPIKE_FINDINGS.md)
    -> persist turns, return reply.

Tenant scoping: every query filters by tenant_id. Sessions/agents belong to a
tenant; a session row is only ever loaded WHERE tenant_id = %s AND ...

Tools:
  - get_time: trivial pure tool
  - quill_finance_summary: GET {QUILL_API_URL}/v1/finance/summary with X-Agent-Secret
    (read-only prod call; proves "Quill as a built-in agent capability").

Env:
  DATABASE_URL          Postgres DSN (Cloud SQL, quill DB) — required
  ANTHROPIC_API_KEY     required
  QUILL_API_URL         default https://quill-agents-894031978246.us-central1.run.app
  QUILL_AGENT_SECRET    required for the finance tool
  MODEL                 default claude-haiku-4-5 (spike budget)
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import anthropic
import httpx
import psycopg
from fastapi import FastAPI, HTTPException
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

log = logging.getLogger("agentcloud")
logging.basicConfig(level=logging.INFO)

MODEL = os.environ.get("MODEL", "claude-haiku-4-5")
QUILL_API_URL = os.environ.get(
    "QUILL_API_URL", "https://quill-agents-894031978246.us-central1.run.app"
)
MAX_TOOL_ITERATIONS = 6

DDL = """
CREATE TABLE IF NOT EXISTS agentcloud_tenants (
    tenant_id   TEXT PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS agentcloud_agents (
    tenant_id     TEXT NOT NULL REFERENCES agentcloud_tenants(tenant_id),
    agent_id      TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    model         TEXT NOT NULL,
    tools         JSONB NOT NULL DEFAULT '["get_time","quill_finance_summary"]',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, agent_id)
);
CREATE TABLE IF NOT EXISTS agentcloud_sessions (
    session_id  UUID PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, agent_id)
        REFERENCES agentcloud_agents(tenant_id, agent_id)
);
CREATE INDEX IF NOT EXISTS agentcloud_sessions_tenant_idx
    ON agentcloud_sessions (tenant_id, agent_id);
CREATE TABLE IF NOT EXISTS agentcloud_messages (
    message_id  BIGSERIAL PRIMARY KEY,
    session_id  UUID NOT NULL REFERENCES agentcloud_sessions(session_id),
    tenant_id   TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agentcloud_messages_session_idx
    ON agentcloud_messages (tenant_id, session_id, message_id);
"""

DEFAULT_SYSTEM_PROMPT = (
    "You are a Quill Agent Cloud assistant for tenant {tenant_id}. "
    "You have tools: get_time and quill_finance_summary (real Quill portfolio "
    "financials). Use tools when helpful; answer concisely."
)

TOOLS_SPEC = [
    {
        "name": "get_time",
        "description": "Get the current date and time (America/New_York).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "quill_finance_summary",
        "description": "Get the live Quill portfolio financial summary (ARR, "
        "pipeline, contracts, estimates) from the production Quill API. Read-only.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def db() -> psycopg.Connection:
    # QUILL_DATABASE_URL is stored SQLAlchemy-style (postgresql+asyncpg://...);
    # normalize to a libpq-compatible scheme for psycopg.
    dsn = os.environ["DATABASE_URL"]
    if "+" in dsn.split("://", 1)[0]:
        dsn = "postgresql://" + dsn.split("://", 1)[1]
    return psycopg.connect(dsn, row_factory=dict_row)


def run_tool(name: str, _args: dict) -> str:
    if name == "get_time":
        return datetime.now(ZoneInfo("America/New_York")).strftime(
            "%A %Y-%m-%d %H:%M:%S %Z"
        )
    if name == "quill_finance_summary":
        secret = os.environ.get("QUILL_AGENT_SECRET", "")
        if not secret:
            return json.dumps({"error": "QUILL_AGENT_SECRET not configured"})
        r = httpx.get(
            f"{QUILL_API_URL}/v1/finance/summary",
            headers={"X-Agent-Secret": secret},
            timeout=30,
        )
        if r.status_code != 200:
            return json.dumps({"error": f"quill api {r.status_code}", "body": r.text[:500]})
        return r.text
    return json.dumps({"error": f"unknown tool {name}"})


class ChatIn(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    agent_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=8000)
    session_id: uuid.UUID | None = None


class ChatOut(BaseModel):
    session_id: uuid.UUID
    reply: str
    tool_calls: list[str]
    model: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    with db() as conn:
        conn.execute(DDL)
        conn.commit()
    log.info("agentcloud DDL ensured")
    yield


app = FastAPI(title="quill-agent-orchestrator (spike)", lifespan=lifespan)


@app.get("/healthz")
def healthz():
    return {"ok": True, "model": MODEL}


@app.post("/v1/agents/chat", response_model=ChatOut)
def chat(body: ChatIn):
    client = anthropic.Anthropic()
    with db() as conn:
        # Tenant + agent upsert (spike convenience; prod = signup provisioning).
        conn.execute(
            "INSERT INTO agentcloud_tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (body.tenant_id,),
        )
        conn.execute(
            """INSERT INTO agentcloud_agents (tenant_id, agent_id, system_prompt, model)
               VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
            (
                body.tenant_id,
                body.agent_id,
                DEFAULT_SYSTEM_PROMPT.format(tenant_id=body.tenant_id),
                MODEL,
            ),
        )
        agent = conn.execute(
            "SELECT * FROM agentcloud_agents WHERE tenant_id = %s AND agent_id = %s",
            (body.tenant_id, body.agent_id),
        ).fetchone()

        # Session: load only if it belongs to THIS tenant (isolation from row one).
        if body.session_id:
            sess = conn.execute(
                """SELECT * FROM agentcloud_sessions
                   WHERE session_id = %s AND tenant_id = %s AND agent_id = %s""",
                (body.session_id, body.tenant_id, body.agent_id),
            ).fetchone()
            if not sess:
                raise HTTPException(404, "session not found for this tenant/agent")
            session_id = sess["session_id"]
        else:
            session_id = uuid.uuid4()
            conn.execute(
                """INSERT INTO agentcloud_sessions (session_id, tenant_id, agent_id)
                   VALUES (%s, %s, %s)""",
                (session_id, body.tenant_id, body.agent_id),
            )

        rows = conn.execute(
            """SELECT role, content FROM agentcloud_messages
               WHERE tenant_id = %s AND session_id = %s
               ORDER BY message_id""",
            (body.tenant_id, session_id),
        ).fetchall()
        history = [{"role": r["role"], "content": r["content"]} for r in rows]
        conn.commit()

    messages = history + [{"role": "user", "content": body.message}]
    new_turns: list[dict] = [{"role": "user", "content": body.message}]
    tool_calls: list[str] = []
    reply = ""

    for _ in range(MAX_TOOL_ITERATIONS):
        resp = client.messages.create(
            model=agent["model"],
            max_tokens=1024,
            system=agent["system_prompt"],
            tools=TOOLS_SPEC,
            messages=messages,
        )
        assistant_content = [b.model_dump(exclude_none=True) for b in resp.content]
        messages.append({"role": "assistant", "content": assistant_content})
        new_turns.append({"role": "assistant", "content": assistant_content})
        if resp.stop_reason != "tool_use":
            reply = "".join(b.text for b in resp.content if b.type == "text")
            break
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                tool_calls.append(block.name)
                out = run_tool(block.name, block.input or {})
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": out}
                )
        messages.append({"role": "user", "content": results})
        new_turns.append({"role": "user", "content": results})
    else:
        reply = "(tool iteration limit reached)"

    with db() as conn:
        for turn in new_turns:
            conn.execute(
                """INSERT INTO agentcloud_messages (session_id, tenant_id, role, content)
                   VALUES (%s, %s, %s, %s)""",
                (session_id, body.tenant_id, turn["role"], json.dumps(turn["content"])),
            )
        conn.execute(
            "UPDATE agentcloud_sessions SET updated_at = %s WHERE session_id = %s AND tenant_id = %s",
            (datetime.now(timezone.utc), session_id, body.tenant_id),
        )
        conn.commit()

    return ChatOut(session_id=session_id, reply=reply, tool_calls=tool_calls, model=agent["model"])
