# quill-agent-orchestrator — Quill Agent Cloud platform core (Phase A, Sprints A1–A6)

Contracts in this directory: `EVENTS.md` (events + jobs + wakes),
`WEBCHAT.md` (A5 web-chat channel + read endpoints + api bridge),
`APPROVALS.md` (A6 approval-gated writes through the Quill /queue),
`TENANCY.md` (B1 per-user tenancy, signup provisioning, isolation attack
suite).

**Tenancy (B1):** every Quill user gets a personal tenant
(`user-{user.id}`, derived server-side from the JWT by the api bridge —
never client-supplied); owner/partner may additionally select the shared
org tenant (`AGENTCLOUD_TENANT_ID`, default `quill-main`, all pre-B1 data)
via the bridge's `workspace=org`. Tenants are provisioned idempotently on
first contact (signup hook + lazy fallback). Isolation is proven by the
attack suite: `tests/test_isolation.py` (app layer) and
`tests/test_isolation_pg.py` (a systematic RLS sweep over every table in
`migrations._RLS_TABLES`, pg-gated). See `TENANCY.md`.

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
│   ├── scheduler.py        # A4: per-tenant cron/reminder schedules + tick loop (+ A6 reconcile sweep)
│   ├── approvals.py        # A6: proposal create/finalize/reconcile (APPROVALS.md)
│   ├── directory.py        # A5: agents/sessions/transcript reads (WEBCHAT.md §3)
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
│       ├── quill.py        # 6 read-only X-Agent-Secret tools
│       └── quill_writes.py # A6: 5 approval-gated write tools (proposal-only)
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
  `{claimed, fired, failed}` (+ `approvals_checked`/`approvals_resolved`
  when the A6 reconcile sweep touched anything).

- `GET /v1/agents/usage?tenant_id=…` (B2, contract: `LIMITS.md` §2) →
  current-month usage/meters: `{month, tenant{budget_monthly_usd,
  budget_source: default|override, spend_usd, remaining_usd, input_tokens,
  output_tokens, requests, exhausted}, agents:[{agent_id, budget_monthly_usd,
  spend_usd, remaining_usd, input_tokens, output_tokens, requests,
  exhausted}]}`. Every defined agent appears (zero-usage included, ordered by
  `agent_id`); tenant totals include usage from agents deleted mid-month.
  Provisions the tenant + seeds idempotently first. Exposed to the browser
  via the api bridge `GET /v1/agent-cloud/usage?workspace=personal|org`.

- A5 read endpoints (contract + payload shapes: `WEBCHAT.md` §3):
  `GET /v1/agents?tenant_id=…` (agent directory; provisions tenant + seeds
  idempotently), `GET /v1/agents/sessions?tenant_id=…&agent_id?=` (sessions,
  newest-updated first), `GET /v1/agents/sessions/{id}?tenant_id=…` (full
  transcript). The human-facing path goes through the api bridge
  (`/v1/agent-cloud/*`, JWT-gated, server-side tenant injection — see
  `WEBCHAT.md` §4) and the web `/assistant` page.

- A6 (contract: `APPROVALS.md`): write tools never mutate Quill directly —
  they queue `agentcloud.*` approval items and record `agentcloud_proposals`
  rows. `POST /v1/internal/approvals/notify` (header
  `X-Agent-Secret: $APPROVALS_NOTIFY_SECRET`, 403/disabled while unset) is
  the api’s best-effort resolution push; the scheduler tick’s reconcile
  sweep is the polling fallback. Both finalize idempotently and wake the
  originating session.

Errors use the standard envelope `{"detail": "..."}` (404 unknown
agent/session incl. cross-tenant attempts, 403 disabled agent, 502 provider,
429 rate-limited with `Retry-After`).

## B2 — budgets, rate limits, per-tenant secrets (`LIMITS.md`, `SECRETS.md`)

**Tenant budgets** (`LIMITS.md` §1). Two monthly caps gate every turn
(chat, sub-agent job, scheduled fire): the per-agent cap
(`agentcloud_agents.budget_monthly_usd`) and the tenant-total cap
(`agentcloud_tenants.budget_monthly_usd`, summed across all the tenant's
agents). A NULL tenant value defers to config: `user-*` personal tenants get
`TENANT_BUDGET_DEFAULT_USD` ($10), everything else gets
`ORG_TENANT_BUDGET_USD` ($100). Exceeding either → a polite refusal (never a
model call, never an HTTP error); the agent cap wins precedence when both are
exhausted, and the refusal text names the workspace when the tenant cap is
the one that tripped. This fixes the KNOWN_ISSUES B1 per-user blowup
(N users × 2 seed agents × $20/mo). Set/clear an explicit override:
`python -m app.admin set-tenant-budget --tenant … --budget 25`
(`--budget default` clears back to NULL).

**Rate limits** (`LIMITS.md` §3). Per-tenant fixed-window (1 min) counters in
the shared Postgres (`agentcloud_rate_limits`): `chat` bucket
(`POST /v1/agents/chat`, `RATE_LIMIT_PER_MIN`, default 30) and `jobs` bucket
(`POST /v1/agents/subagents` + `POST /v1/agents/schedules`,
`RATE_LIMIT_JOBS_PER_MIN`, default 10). `0` disables a bucket. Over-limit →
`429 {detail}` + `Retry-After`; on the SSE path the check runs before the
stream so it is a plain 429, never an SSE error. Multi-instance-safe with no
Redis (same shared-Postgres discipline as the SKIP LOCKED scheduler claim);
the documented tradeoff is that a fixed window allows ≤2× burst across a
boundary — acceptable for an abuse limit. `rate_limit.exceeded` is evented at
most once per (tenant, bucket, minute) so an abusive client cannot flood the
events table.

**Per-tenant secrets** (`SECRETS.md`). `agentcloud_tenant_secrets` (RLS'd)
+ a config-gated provider (`SECRETS_BACKEND`): `plaintext-dev` (default;
dev/tests, value stored raw) or `kms` (AES-256-GCM envelope: fresh DEK per
value, AAD binds ciphertext to tenant+name, DEK wrapped by Cloud KMS; the KEK
never touches the DB). All access goes through `app/secrets.py`
(`set/get/delete/list_secrets`; list never returns values). No HTTP surface
in B2 — the first consumer (per-tenant channel adapters) arrives in Phase C.
One-time KMS setup (app code never creates GCP resources):

```bash
gcloud kms keyrings create agentcloud \
  --project totemic-formula-467102-s9 --location us-central1
gcloud kms keys create tenant-secrets \
  --project totemic-formula-467102-s9 --location us-central1 \
  --keyring agentcloud --purpose encryption \
  --rotation-period 90d --next-rotation-time +90d
gcloud kms keys add-iam-policy-binding tenant-secrets \
  --project totemic-formula-467102-s9 --location us-central1 --keyring agentcloud \
  --member serviceAccount:openclaw-adk@totemic-formula-467102-s9.iam.gserviceaccount.com \
  --role roles/cloudkms.cryptoKeyEncrypterDecrypter
# then on deploy:
#   SECRETS_BACKEND=kms
#   SECRETS_KMS_KEY=projects/totemic-formula-467102-s9/locations/us-central1/keyRings/agentcloud/cryptoKeys/tenant-secrets
```

## C — Agent Builder (`AGENT_BUILDER.md`)

Phase C productizes “agents are data” (design §3.3): users create/edit/tune
their own agents over the `agentcloud_agents` row through the web app. Contract:
`AGENT_BUILDER.md` (read it before touching builder code).

**agent-cloud CRUD** (`app/agents.py`, tenant-scoped + RLS'd like every read,
`{detail}` envelope, 404-not-403 cross-tenant):
- `POST /v1/agents` (create) — 201 detail; 400 validation, 409 duplicate slug.
- `GET /v1/agents/{agent_id}` — detail (superset of the A5 list dict: adds
  `system_prompt`, `tools`, `is_seed`).
- `PATCH /v1/agents/{agent_id}` — partial update (prompt/model/tools/
  memory_policy/budget/enabled); 400 validation, 403 seed-protected, 404.
- `DELETE /v1/agents/{agent_id}` — **soft-delete** (`enabled=false`); sessions/
  memory/usage/history are never hard-deleted; 403 for seeds.
- `GET /v1/agents/catalog` — tool palette grouped from the REGISTRY (source of
  truth) with human labels + `approval_gated`/`memory_tool` flags + allowed
  models + memory policies.
- `GET /v1/agents/templates` — 3 static clone-to-create starters
  (Research Assistant / Ops Analyst / Project Copilot).

**Server-side validation** (authoritative; the form only mirrors it): `agent_id`
slug rule + per-tenant uniqueness; `system_prompt` ≤ `SYSTEM_PROMPT_MAX_CHARS`
(8000); `tools` ⊆ the registry catalog; `model` ∈ the pricing-table alias set
(`claude-fable-5`/`-sonnet-4-6`/`-haiku-4-5`); `budget_monthly_usd` > 0 and ≤
the tenant cap (LIMITS.md §1); `memory_policy` enum. **Seed protection**
(`personal`/`quill`): can be tuned (prompt/tools/model/memory/budget) but never
deleted, disabled, or renamed (`is_seed` derives from `SEED_AGENTS`, so a future
seed is auto-protected). Route order note: the `{agent_id}` path routes are
registered *after* the literal `/v1/agents/{usage,sessions,subagents,schedules,
catalog,templates}` routes so a literal is never shadowed.

**Events:** `agent.updated` (`{action: created|updated|deleted, fields:[...]}`),
written durably in the same tenant tx and published best-effort (EVENTS.md /
AGENT_BUILDER.md §9). Never fails the CRUD call.

**api bridge** (`/v1/agent-cloud/agents` + `/catalog` + `/templates`,
`AGENT_BUILDER.md §8`): JWT-gated, server-side tenant (`workspace=personal|org`,
org → owner/partner), identical `{detail}`/502 semantics as the A5 read bridge;
client-sent `tenant_id` is never a schema field.

**Web UI:** `/assistant/builder` (top-level `/agents` is the pre-existing ADK
Agent Registry — not reused). Agent list (seeds badged) + create-from-template;
editor form (slug/prompt/model/memory/budget/enabled); grouped tool palette with
write tools clearly marked and an approval-queue notice when any is enabled
(APPROVALS.md tie-in); a test console that reuses the chat SSE against the saved
agent. The `/assistant` chat page links to it.

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
