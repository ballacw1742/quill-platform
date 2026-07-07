# quill-agent-orchestrator — Quill Agent Cloud platform core (Phase A, Sprints A1–A4)

Multi-tenant agent orchestrator on Cloud Run. Hardened from the P0 spike
(`SPIKE_FINDINGS.md`) per the design doc
(`gcp-agent-platform/QUILL-AGENT-CLOUD-DESIGN.md` §3, §5, §6, §7).

## Layout

```
agent-cloud/
├── main.py                 # uvicorn shim → app.api:app
├── app/
│   ├── config.py           # env settings (pydantic-settings)
│   ├── logging_setup.py    # JSON logs + request/tenant/agent/session contextvars
│   ├── db.py               # async SQLAlchemy, pooling, tenant_session() GUC helper
│   ├── models.py           # ORM for agentcloud_* tables
│   ├── migrations.py       # additive idempotent DDL + RLS policies (own-DDL pattern)
│   ├── budget.py           # usage metering + monthly hard cap (polite refusal)
│   ├── events.py           # A3: event bus (inline|pubsub) + durable event rows
│   ├── jobs.py             # A3: sub-agent jobs (local|cloudrun) + CLI entrypoint
│   ├── scheduler.py        # A4: per-tenant cron/reminder schedules + tick loop
│   ├── memory.py           # A2: memory save/search core (pgvector + text fallback)
│   ├── seeds.py            # per-tenant "personal" + "quill" agent definitions
│   ├── orchestrator.py     # the chat/tool loop (stream + non-stream)
│   ├── api.py              # FastAPI: /health, chat, subagents, schedules, tick
│   ├── admin.py            # maintenance CLI (Cloud Run job): rls-probe, set-agent, …
│   ├── providers/          # ModelProvider interface
│   │   ├── anthropic_direct.py   # live today (ANTHROPIC_API_KEY)
│   │   ├── vertex_anthropic.py   # config-gated; clean error while quota=0
│   │   ├── pricing.py            # $/MTok table (PRICING_JSON override)
│   │   └── embeddings.py         # A2: EMBEDDING_PROVIDER=gemini|vertex|none
│   └── tools/              # registry keyed by name; allow-list enforced twice
│       ├── builtin.py      # get_time
│       ├── memory.py       # A2: memory_save + memory_search
│       └── quill.py        # 6 read-only X-Agent-Secret tools
└── tests/                  # pytest (sqlite unit; pg-gated RLS integration)
```

## Architecture notes

- **Pooling:** one async engine per process (`asyncpg`), `pool_size=5`,
  `max_overflow=10`, `pool_pre_ping`, 30-min recycle. No connection is held
  during model calls — a turn is tx1 (load) → model loop → tx2 (persist).
- **Isolation (belt + suspenders):** every query filters `tenant_id`
  (app layer) **and** all `agentcloud_*` tables have
  `ENABLE`+`FORCE ROW LEVEL SECURITY` with a policy on
  `current_setting('app.tenant_id', true)`, set per-transaction via
  `set_config(..., is_local=true)` so pooled connections can't leak tenants.
  A second OR'd policy (`app.admin = 'on'`) exists solely for the
  maintenance CLI; the request path never sets it.
- **Providers:** `MODEL_PROVIDER=anthropic|vertex` selects the client at
  runtime; both normalize to the same `ModelResponse` (content blocks +
  token usage). Retry/backoff (3 attempts, exponential + jitter) on
  429/5xx/connection errors. Vertex fails cleanly with a quota hint until
  the filed quota increase lands (SPIKE_FINDINGS.md).
- **Agents are data:** `agentcloud_agents(system_prompt, model, tools JSONB,
  budget_monthly_usd, enabled)`. First tenant contact seeds `personal` and
  `quill` (design §3.3). Tool allow-lists are enforced twice: only listed
  tools are sent to the model, and `run_tool()` re-checks before executing.
- **Budgets:** `agentcloud_usage` upserts per (tenant, agent, day). At the
  cap the turn returns a persisted, polite refusal (`budget_exceeded: true`)
  and makes zero model calls.
- **Memory (A2):** `agentcloud_memory` — long-term memory rows namespaced by
  `(tenant_id, agent_id)` with `kind` (fact/preference/summary), JSONB
  metadata, and a pgvector `embedding vector(EMBEDDING_DIM=768)` column
  (RLS'd like every other agentcloud_* table). Embeddings are config-gated
  like MODEL_PROVIDER: `EMBEDDING_PROVIDER=gemini` (Gemini API direct,
  `GEMINI_API_KEY` — the live path today) | `vertex` (IAM; clean quota-hint
  error until the Vertex quota lands) | `none`. Embedding calls happen
  *outside* DB transactions (same no-conn-during-network discipline).
  **Everything degrades cleanly:** no key / no pgvector ⇒ memories still
  save (without vectors) and `memory_search` falls back to keyword (ILIKE)
  search. `CREATE EXTENSION vector` is attempted at migration time and
  tolerated if privileges are missing (Cloud SQL supports pgvector; the
  extension may need one-time creation by a privileged role — see
  KNOWN_ISSUES.md).
- **memory_policy (per agent, agent-definitions-as-data):**
  `off` (memory tools stripped from the effective allow-list, no recall) |
  `tools_only` (explicit `memory_save`/`memory_search` tool calls only) |
  `auto_recall` (tools + the orchestrator injects the top
  `MEMORY_RECALL_TOP_K` (5) relevant memories into the system prompt at
  turn start, capped at `MEMORY_RECALL_MAX_CHARS` (2000)). Seeds: `personal`
  = `auto_recall` (memory on, per design §3.3); `quill` = `off`. Override:
  `python -m app.admin set-agent --memory-policy …`. Recall runs after the
  budget gate and is best-effort — it can never fail a turn.
- **Events (A3):** contract in `EVENTS.md` (read it before touching event
  code). Every event is written durably to `agentcloud_events` (RLS'd,
  tenant-namespaced) in the same tx2 that persists the turn/job, then
  published best-effort via `EVENT_BUS=inline|pubsub` — a publish failure is
  logged and can never fail a user turn. Emitted: `turn.completed`,
  `tool.executed`, `budget.exceeded`, `subagent.started/completed/failed`.
  Pub/Sub topic `agentcloud-events` (+ `agentcloud-events-deadletter`,
  max 5 delivery attempts) — topics/subscriptions are created ops-side.
- **Sub-agent jobs (A3):** `agentcloud_jobs` rows
  (queued|running|ok|error|timeout) executed per `JOBS_BACKEND`:
  `local` = in-process asyncio task (dev/tests); `cloudrun` = one Cloud Run
  Job execution of `CLOUDRUN_JOB_NAME` running `python -m app.jobs run
  <job_id>` (env `JOB_ID`/`JOB_TENANT_ID` are set per execution). A job is a
  normal orchestrator turn in a fresh sub-session — same budget rows, same
  refusal semantics (a budget refusal is a *completed* job with
  `result.budget_exceeded=true`). On completion the parent session (if any)
  gets exactly one `[system wake]` user-role message in the same tx that
  finalizes the job (wake semantics in EVENTS.md).
- **Schedules (A4):** `agentcloud_schedules` (RLS'd like every other
  `agentcloud_*` table) — per-tenant cron + one-shot reminders per the
  design's “Cloud Scheduler (cron/reminders per tenant)” slice. A schedule
  is `kind='cron'` (`cron_expr` evaluated with croniter in an IANA
  `timezone`) or `kind='at'` (one-shot `run_at`); `next_run_at` is always
  stored UTC. When due, a schedule fires **through the A3 jobs machinery**:
  `jobs.create_job` enqueues an `agentcloud_jobs` row whose task is the
  schedule's `payload.message`, so budget metering, refusal semantics,
  tool allow-lists and `subagent.*` events apply unchanged; `schedule.fired`
  / `schedule.failed` are emitted per EVENTS.md. **Claiming is
  multi-instance-safe:** the tick selects due rows with
  `FOR UPDATE SKIP LOCKED` and advances `next_run_at` (cron → next
  occurrence, one-shot → NULL) inside the same locked transaction, so two
  orchestrator instances can never double-fire. The claim scans across
  tenants and therefore runs under the admin RLS policy (a system path,
  like the maintenance CLI); all per-schedule writes go back through
  tenant-scoped transactions. One-shot schedules with
  `delete_after_run=true` are deleted after a successful fire; a failed
  fire keeps the row with `last_status='error: …'` (a failed one-shot is
  parked — PATCH it to reschedule). Tick delivery is config-gated
  (`SCHEDULER_BACKEND`): `loop` = in-process asyncio task every
  `SCHEDULER_TICK_SECONDS` (30) started on app startup — dev/local and the
  single-instance default; `cloudscheduler` = no in-process loop, a Cloud
  Scheduler HTTP job POSTs `/v1/internal/scheduler/tick` (see §Deploy).
- **Reminders (A4):** a reminder is just a schedule whose `message` says
  what to remind about, with `session_id` set to the target session. The
  fired job runs a normal agent turn in a fresh sub-session — the
  assistant's reply *is* the reminder — and, per the EVENTS.md wake
  contract, completion inserts one `[system wake]` message into the target
  session (Phase A: the wake is passive; the user/agent sees it on the next
  turn, and proactive re-invocation is a later slice).
- **Model tiering:** seeds use `MODEL_DEFAULT` (claude-fable-5); tenants with
  the `smoke-` prefix seed on `MODEL_CHEAP` (claude-haiku-4-5) so test loops
  stay cheap. Per-agent overrides via `python -m app.admin set-agent`.

## Health checks — read this before "fixing" a 404

Google's frontend intercepts the literal path **`/healthz`** on `*.run.app`
and returns its own HTML 404 before the request reaches the container
(verified 2026-07-06: `GET /` and `GET /health` reach FastAPI; `GET /healthz`
never does, on both the numeric and `qdur2ylusq` URL forms). This was the
spike's unexplained "GFE 404" caveat. **External health checks must use
`GET /health`.** `/healthz` remains registered for container-internal probes
only.

## API

- `GET /health` → `{ok, service, model_provider, db}` (503 if DB down).
- `POST /v1/agents/chat` `{tenant_id, agent_id, message, session_id?, stream?}`
  - non-stream → `{session_id, reply, tool_calls, model, usage{input_tokens,
    output_tokens, cost_usd}, budget_exceeded}`
  - `stream: true` → SSE events: `session`, `text` (`{delta}`),
    `tool` (`{name, status: start|ok|denied}`), `done` (full result),
    `error` (`{detail, status}`).

- `POST /v1/agents/subagents` `{tenant_id, agent_id, task, session_id?}`
  (session_id = parent session to wake) → `202 {job_id, status: "queued"}`.
- `GET /v1/agents/subagents/{job_id}?tenant_id=…` → full job record
  `{job_id, status, result{reply, session_id, usage, budget_exceeded},
  error, …timestamps}`.

- `POST /v1/agents/schedules` `{tenant_id, agent_id, name, kind: "at"|"cron",
  cron_expr?, timezone? (IANA, default UTC), run_at?, message, session_id?,
  enabled?, delete_after_run?}` → `201` full schedule record (incl.
  `next_run_at` in UTC). 400 invalid cron/timezone/timing, 404 unknown
  agent or target session, 403 disabled agent.
- `GET /v1/agents/schedules?tenant_id=…&limit=&offset=` →
  `{items, total, limit, offset}` (tenant-scoped).
- `GET /v1/agents/schedules/{id}?tenant_id=…` → schedule record (404
  cross-tenant, same semantics as subagents).
- `PATCH /v1/agents/schedules/{id}?tenant_id=…` — partial update
  (`enabled`, `message`, timing fields…); any timing change or re-enable
  recomputes `next_run_at`.
- `DELETE /v1/agents/schedules/{id}?tenant_id=…` → 204.
- `POST /v1/internal/scheduler/tick` — internal (Cloud Scheduler)
  entrypoint; requires header `X-Agent-Secret: $SCHEDULER_TICK_SECRET`
  (403 otherwise; endpoint is disabled while the secret is unset). Returns
  `{claimed, fired, failed}`.

Errors use the standard envelope `{"detail": "..."}` (404 unknown
agent/session incl. cross-tenant attempts, 403 disabled agent, 502 provider).

## Deploy

CI: `.github/workflows/agentcloud-deploy.yml` (paths `agent-cloud/**`) —
pytest → docker build → `gcloud run deploy` with `--update-env-vars` /
`--update-secrets` (backend-deploy conventions). Secrets:
`DATABASE_URL=QUILL_DATABASE_URL`, `ANTHROPIC_API_KEY`, `QUILL_AGENT_SECRET`,
`GEMINI_API_KEY` (rotated 2026-07-06; enables A2 semantic embeddings via
`EMBEDDING_PROVIDER=gemini`).

A3 flags default safe (`EVENT_BUS=inline`, `JOBS_BACKEND=local`). Flipping to
`pubsub`/`cloudrun` additionally needs ops-side resources (not created by
app code): the two Pub/Sub topics + subscription with dead-letter policy
(EVENTS.md), and a `agentcloud-subagent` Cloud Run Job on this image with
`--command python --args -m,app.jobs,run` + the same secrets, plus
`run.jobs.run` IAM on the service account.

Scheduler: default `SCHEDULER_BACKEND=loop` needs nothing ops-side (the
process ticks itself every `SCHEDULER_TICK_SECONDS`; fine for a
single-instance service, and safe — not duplicate-firing — even with
several instances thanks to the SKIP LOCKED claim). For
`SCHEDULER_BACKEND=cloudscheduler` (no in-process loop; Cloud Run can then
scale to zero between ticks), create the one-time Cloud Scheduler job — app
code never creates GCP resources:

```bash
# secret shared with the service (also set SCHEDULER_TICK_SECRET on deploy)
gcloud secrets create AGENTCLOUD_SCHEDULER_TICK_SECRET --project totemic-formula-467102-s9
gcloud scheduler jobs create http agentcloud-scheduler-tick \
  --project totemic-formula-467102-s9 --location us-central1 \
  --schedule "* * * * *" \
  --uri https://<service-url>/v1/internal/scheduler/tick \
  --http-method POST \
  --headers X-Agent-Secret=<the-secret> \
  --oidc-service-account-email openclaw-adk@totemic-formula-467102-s9.iam.gserviceaccount.com
```

The endpoint is defense-in-depth: OIDC/IAM gates ingress and the
X-Agent-Secret header is verified in-app (same shared-secret pattern as the
Quill tool suite). Minute-level granularity: with the Cloud Scheduler
backend, schedules fire up to ~60s late by design.

Maintenance job (one-time create; CI keeps its image fresh):

```bash
gcloud run jobs create agentcloud-admin \
  --image gcr.io/totemic-formula-467102-s9/quill-agent-orchestrator:<sha> \
  --region us-central1 --project totemic-formula-467102-s9 \
  --service-account openclaw-adk@totemic-formula-467102-s9.iam.gserviceaccount.com \
  --set-cloudsql-instances totemic-formula-467102-s9:us-central1:quill-datasite-db \
  --set-secrets DATABASE_URL=QUILL_DATABASE_URL:latest \
  --command python --args -m,app.admin,rls-probe
# then per run:
gcloud run jobs execute agentcloud-admin --region us-central1 --wait \
  --args -m,app.admin,<subcommand>,<flags...>
```

## Tests

```bash
cd agent-cloud && pip install -r requirements-dev.txt && pytest -q
```

- Unit + app-layer isolation + budget + SSE + memory + scheduler tests run
  on sqlite (no network, no keys — model provider is faked; embeddings
  short-circuit to the text-search fallback).
- `tests/test_rls_pg.py` + `tests/test_memory_pg.py` +
  `tests/test_scheduler_pg.py` need Postgres: set
  `AGENTCLOUD_TEST_PG_DSN` (a **non-superuser** role — superusers bypass
  RLS and the isolation tests will fail spuriously). test_memory_pg also
  proves migration idempotency (runs twice) and pgvector cosine ordering
  (skips that one test cleanly if the extension is unavailable).
  In prod the equivalent proof is `python -m app.admin rls-probe` as the
  Cloud Run job (raw SQL as the app role; wrong/missing GUC ⇒ zero rows).
- Needs the deployed service (not covered by pytest): IAM-gated ingress,
  Cloud SQL socket connectivity, live Anthropic/Vertex calls, live Quill
  tool calls.
