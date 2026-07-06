# Quill Agent Cloud — Phase A P0 Spike Findings

**Date:** 2026-07-06 evening · **Branch:** `agentcloud-p0-spike` · **Verdict: GO**

## Verdict

**GO for Phase A.** The full loop works in prod tonight: tenant-scoped orchestrator on
Cloud Run → Claude tool loop → Postgres session persistence → real Quill prod data via
`X-Agent-Secret` → cross-tenant isolation enforced and demonstrated. Total spike model
spend well under $1. The only gap is Vertex quota (below) — it does not block Phase A
because Anthropic-direct works today and the model client is a one-line swap.

## Vertex AI Claude status (goal 1)

| Finding | Detail |
|---|---|
| Model Garden listing | `publishers/anthropic/models/claude-fable-5`, `claude-sonnet-4-6`, `claude-haiku-4-5` (and opus-4-x, sonnet-5) all listed in project `totemic-formula-467102-s9` |
| Regions | **`global` endpoint only** for these models — `us-east5` and `us-central1` return 404 (`Publisher model ... not found`) for fable-5/haiku-4-5/sonnet-4-6 |
| Data sharing | Was disabled; enabled tonight via `setPublisherModelConfig` (`dataSharingEnabledProvider: ANTHROPIC`) — one-time per-project step, done |
| Invocation | **Blocked by quota:** every `rawPredict` call returns 429 `Quota exceeded for aiplatform.googleapis.com/global_online_prediction_requests_per_base_model` — default quota for these base models is effectively 0; requires a quota increase request (console, async approval) |
| Fallback used | **Anthropic API direct** (`ANTHROPIC_API_KEY` in Secret Manager). `claude-fable-5` invoked successfully direct (`SPIKE-FABLE-OK`, 27 in / 45 out tokens). Orchestrator runs `claude-haiku-4-5` direct. |
| Pricing parity | Per Google's published Model Garden pricing, Vertex Claude token pricing matches Anthropic direct list pricing (parity per design doc §7); the difference is auth (IAM vs API key) and billing surface (GCP invoice) |

**Action for Phase A:** file the Vertex quota increase request for
`global_online_prediction_requests_per_base_model` (anthropic-claude-fable-5,
-sonnet-4-6, -haiku-4-5) now; build the model client with a provider switch
(`vertex|anthropic`) so cutover is config, not code.

## What was built (goals 2–4)

- **`agent-cloud/main.py`** — FastAPI orchestrator: `POST /v1/agents/chat
  {tenant_id, agent_id, message, session_id?}`. Own DDL (dispatch-worker pattern, no
  alembic): `agentcloud_tenants`, `agentcloud_agents`, `agentcloud_sessions`,
  `agentcloud_messages`. Every session/message query filters `tenant_id`; sessions load
  only `WHERE session_id AND tenant_id AND agent_id`.
- **Tools:** `get_time` (pure) and `quill_finance_summary` (prod
  `GET /v1/finance/summary` with `X-Agent-Secret` from Secret Manager). Full
  assistant/tool_use/tool_result turns persisted as JSONB.
- **Deployed:** Cloud Run `quill-agent-orchestrator` (us-central1), revision
  `quill-agent-orchestrator-00002-x95`, `--no-allow-unauthenticated`, min-instances=0,
  Cloud SQL `quill-datasite-db` attached, secrets via `--update-secrets`
  (DATABASE_URL=QUILL_DATABASE_URL, ANTHROPIC_API_KEY, QUILL_AGENT_SECRET), SA
  `openclaw-adk@...`. URL: https://quill-agent-orchestrator-894031978246.us-central1.run.app

## Gate evidence (goal 5)

1. **Multi-turn memory:** tenant-a turn 1 "favorite color is teal" → turn 2 (same
   session_id) correctly answered "teal" + used `get_time` (Mon 2026-07-06 7:06 PM EDT).
2. **Quill tool with real prod numbers:** turn 3 → `quill_finance_summary` → "Current
   ARR: $18,000,000, Pipeline: $23,500,000" (matches prod demo data). ~2.1s end-to-end.
3. **Cross-tenant isolation:** tenant-b POSTing tenant-a's session_id → **HTTP 404
   `session not found for this tenant/agent`**; tenant-b fresh session has no knowledge
   of tenant-a history.
4. **Auth path:** service requires IAM identity token (unauthenticated request rejected);
   model auth = Anthropic API key (Secret Manager) until Vertex quota lands.

## Latency notes

- Plain turn (no tool): ~2–4 s. Tool turn (finance): ~2.1 s measured (warm).
- Cold start (min-instances=0): several seconds extra; Phase A should use
  min-instances=1 for the orchestrator per design doc run-cost estimate.

## What Phase A should reuse / change

**Reuse:** the schema shape (add memory/budgets/schedules tables), the tool-loop +
JSONB turn persistence, the deploy recipe (source deploy, secret refs, Cloud SQL
attach), `X-Agent-Secret` Quill tool pattern, tenant-scoped-query discipline.

**Change:**
- Provider-switchable model client (Vertex IAM once quota granted; `global` endpoint,
  not regional).
- Postgres RLS as second belt (spike is app-layer only).
- Connection pooling (spike opens a connection per request) and async DB driver.
- Real tenant provisioning + auth on the endpoint (spike upserts tenants on first
  message; fine behind IAM, not for product).
- Pub/Sub ingress per §3.1 rather than synchronous HTTP.
- Message claim/lease (reuse dispatch-worker semantics) for channel-driven traffic.

## Risks

- **Vertex quota approval time unknown** — mitigation: Anthropic-direct works; parity
  pricing; switch later. (visible-tolerable)
- **DSN secret is SQLAlchemy-style** (`postgresql+asyncpg://`); spike normalizes the
  scheme in code — Phase A should standardize the secret or the client. (invisible)
- Per-request DB connections won't scale past spike traffic. (invisible at spike scale)
- Odd behavior: authenticated `GET /healthz` returns a Google-frontend 404 while
  `POST /v1/agents/chat` works with the same identity token — did not root-cause
  (suspect GFE/IAM handling of the GET path); health should be re-verified in Phase A.
  (visible-tolerable, ops-only)
- No budget metering yet — spike relies on max_tokens + IAM-gated ingress. (invisible)

## Spend

~30 haiku turns + 1 Fable 5 call ≈ **< $0.25** (budget $5).
