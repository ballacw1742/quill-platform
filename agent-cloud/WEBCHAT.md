# WEBCHAT.md — Quill web-chat channel contract (A5)

This is the canonical contract for the Phase A "web-chat channel" slice
(design doc §4 "Web chat — ship first"): the Quill web app surfaces the
agent-cloud orchestrator through an authenticated bridge in the Quill API.
All three layers — the agent-cloud read endpoints, the Quill API bridge, and
the web frontend — consume exactly these shapes. Do not invent fields
outside this document; extend it here first (same rule as EVENTS.md).

```
browser (Quill web, JWT)             Quill API (bridge)            agent-cloud
  POST /api/v1/agent-cloud/chat ───▶  POST /v1/agent-cloud/chat ─▶  POST /v1/agents/chat
  (Next.js rewrite /api/v1→/v1)       Bearer auth, tenant_id        tenant_id in body,
                                      injected server-side          SSE or JSON back
```

## 1. User → tenant mapping

**Rule: `tenant_id` is a per-deployment server-side constant —
`AGENTCLOUD_TENANT_ID` in the Quill API's settings (default
`quill-<ENVIRONMENT>` is NOT used; the literal default is `quill-main`).**

Why: the design doc (§3.2) defines a tenant as *"= Quill account/org"*, and
today's Quill deployment models exactly one account — there is no org/tenant
column anywhere in the Quill schema (`users` has `id/email/role`, nothing
org-shaped). The faithful derivation is therefore *deployment → tenant*: every
authenticated Quill user of this deployment shares the deployment's tenant
workspace. The client **never** supplies `tenant_id`; the bridge injects it
after `get_current_user` succeeds. Cross-tenant reach from the browser is
structurally impossible — no request field maps to it.

Consequences (documented, accepted for Phase A):

- All users of a deployment share the same agents, sessions, and budgets.
  With the current owner/partner/viewer user base this is the intended
  "org workspace" semantic. Per-user workspaces are the Phase B signup
  provisioning slice (design §7) and will re-derive this rule.
- Smoke/dev environments set `AGENTCLOUD_TENANT_ID=smoke-…` to pick up
  agent-cloud's cheap-model seeding convention.

## 2. Auth

- **Browser → Quill API:** standard Quill session JWT, `Authorization:
  Bearer <jwt>` (localStorage `quill_session_token`, attached by the web
  client exactly like every other route). All bridge routes depend on
  `get_current_user` — 401 without a valid token. **`X-Agent-Secret` is
  never used from the browser.**
- **Quill API → agent-cloud:** server-to-server. Base URL from
  `AGENTCLOUD_URL` (env/Secret-style config, same pattern as
  `DATASITE_URL`). In prod both run on Cloud Run and the call is protected
  the same way as the existing DataSite proxy (network/IAM-level); the
  agent-cloud endpoints themselves are IAM-gated ingress (A1). No secret
  header is required today; if agent-cloud grows in-app inbound auth, the
  bridge adds the header here — never in the browser.

## 3. Bridge API surface (Quill API, all `get_current_user`-gated)

Paths below are the FastAPI paths; the browser reaches them via the existing
Next.js rewrite `/api/v1/:path*` → `/v1/:path*`.

### 3.1 `GET /v1/agent-cloud/agents`

Lists the tenant's agents (seeded on first contact: `personal` + `quill`).
Proxies agent-cloud `GET /v1/agents?tenant_id=…` (new A5 read endpoint,
which provisions the tenant + seed agents idempotently before listing, so a
fresh tenant sees its two agents before ever chatting).

Response `200`:

```json
{
  "items": [
    {
      "agent_id": "personal",
      "model": "claude-fable-5",
      "enabled": true,
      "memory_policy": "auto_recall",
      "budget_monthly_usd": 20.0,
      "created_at": "2026-07-07T12:00:00+00:00"
    }
  ],
  "total": 2, "limit": 100, "offset": 0
}
```

### 3.2 `GET /v1/agent-cloud/sessions?agent_id=…&limit=…&offset=…`

Lists chat sessions for the tenant (optionally filtered by `agent_id`),
newest `updated_at` first. Proxies agent-cloud
`GET /v1/agents/sessions?tenant_id=…`.

Response `200`:

```json
{
  "items": [
    {
      "session_id": "b7f2…-uuid",
      "agent_id": "personal",
      "preview": "first user message, truncated to 120 chars",
      "created_at": "…", "updated_at": "…"
    }
  ],
  "total": 1, "limit": 50, "offset": 0
}
```

`preview` is server-computed (first user text message of the session; empty
string when the session has no plain-text user message yet).

### 3.3 `GET /v1/agent-cloud/sessions/{session_id}`

Full transcript. Proxies agent-cloud
`GET /v1/agents/sessions/{session_id}?tenant_id=…`. 404 for unknown or
cross-tenant session ids (indistinguishable, by design).

Response `200`:

```json
{
  "session_id": "b7f2…-uuid",
  "agent_id": "personal",
  "created_at": "…", "updated_at": "…",
  "messages": [
    { "role": "user", "content": "plain string OR content-block list", "created_at": "…" },
    { "role": "assistant", "content": [{"type": "text", "text": "…"}], "created_at": "…" }
  ]
}
```

**`content` is verbatim what the orchestrator persisted** (the model-wire
shape, EVENTS.md/A1):

- plain `string` — a user chat message,
- `[{type:"text",text}, …]` — assistant text (and the budget refusal),
- `[{type:"text"…},{type:"tool_use",id,name,input}]` — assistant tool call,
- `[{type:"tool_result",tool_use_id,content}]` — user-role tool results,
- `[{type:"text",text:"[system wake] …"}]` — user-role sub-agent wake
  (EVENTS.md wake contract).

Rendering rules (frontend): render text blocks; render `tool_use` as a tool
chip; collapse `tool_result`-only and `[system wake]`-prefixed user messages
into muted system rows. Never crash on an unknown block type — skip it.

### 3.4 `POST /v1/agent-cloud/chat`

Request body (client-supplied; `tenant_id` is injected server-side and any
client attempt to send one is ignored — it is not a field of this schema):

```json
{
  "agent_id": "personal",
  "message": "1–8000 chars",
  "session_id": "uuid or omitted (omitted ⇒ new session)",
  "stream": true
}
```

- `stream: false` (default) → `200 application/json`, agent-cloud's
  non-stream shape passed through verbatim:

```json
{
  "session_id": "…", "reply": "…", "tool_calls": ["get_time"],
  "model": "…",
  "usage": {"input_tokens": 1, "output_tokens": 2, "cost_usd": 0.0003},
  "budget_exceeded": false
}
```

- `stream: true` → `200 text/event-stream`, **SSE events proxied byte-for-
  byte from agent-cloud** (README/A1 contract, unchanged):
  - `event: session` `data: {"session_id": "…"}` — always first
  - `event: text`    `data: {"delta": "…"}` — text deltas
  - `event: tool`    `data: {"name": "…", "status": "start"|"ok"|"denied"}`
  - `event: done`    `data: {session_id, reply, tool_calls, model, usage, budget_exceeded}`
  - `event: error`   `data: {"detail": "…", "status": 404|403|502|500}`

**Budget refusal is not an error:** at the monthly cap the turn streams the
polite refusal as normal `text` + `done` with `budget_exceeded: true`
(non-stream: `200` with `budget_exceeded: true`). The frontend renders a
distinct notice, never an error state.

## 4. Error envelope

Everything non-2xx uses the standard Quill/agent-cloud envelope:

```json
{ "detail": "<string>" }
```

- `401 {"detail": "missing bearer token" | …}` — no/invalid Quill JWT.
- `404` — unknown agent, unknown/cross-tenant session (agent-cloud's own
  404 detail is passed through).
- `403` — disabled agent.
- `502 {"detail": "agent service unreachable"}` — bridge could not reach
  agent-cloud (connection/timeout), or agent-cloud's own 502 (provider
  error) passed through.
- Streaming: transport-level failures after the SSE stream has started
  arrive as a final `event: error` (see 3.4); the frontend shows the detail
  inline and re-enables the composer.

## 5. agent-cloud read endpoints added by A5

The bridge needs three tenant-scoped reads that A1–A4 didn't expose. They
live in agent-cloud (same file conventions as the rest of the API surface),
`tenant_id` as a query param exactly like subagents/schedules:

- `GET /v1/agents?tenant_id=…&limit=…&offset=…` → §3.1 shape. Provisions
  tenant + seed agents (idempotent `INSERT … ON CONFLICT DO NOTHING`, the
  same code path `_prepare` uses) before listing.
- `GET /v1/agents/sessions?tenant_id=…&agent_id=…&limit=…&offset=…` → §3.2
  shape (list envelope `{items, total, limit, offset}`).
- `GET /v1/agents/sessions/{session_id}?tenant_id=…` → §3.3 shape; 404 on
  unknown/cross-tenant.

All are app-layer tenant-filtered **and** RLS-scoped via `tenant_session()`
like every other request path. No write side effects beyond the idempotent
seeding on the agents list.

## 6. Config

| Setting | Where | Default | Meaning |
|---|---|---|---|
| `AGENTCLOUD_URL` | Quill API | `http://localhost:8010` | agent-cloud base URL (Cloud Run URL in prod, Secret/env like `DATASITE_URL`). |
| `AGENTCLOUD_TENANT_ID` | Quill API | `quill-main` | The deployment's tenant id (§1). `smoke-…` prefix ⇒ cheap-model seeds. |
| `AGENTCLOUD_TIMEOUT_SECONDS` | Quill API | `120` | Per-request budget for non-stream calls; streams use no read timeout. |
