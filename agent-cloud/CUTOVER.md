# CUTOVER.md — Quill Agent Cloud go-live runbook (Phase E)

**This is THE document Charles uses to actually go live.** It consolidates
every "code-complete pending external ops" item across Phases A–D into a
single ordered checklist. Each item states: the exact `gcloud`/console steps,
**why** it's external (app code never creates GCP resources — this is a
deliberate security boundary, not a gap), and **the flag/env that activates
it**.

> **Nothing in this document is auto-activated.** The entire platform runs
> today on safe defaults (`EVENT_BUS=inline`, `JOBS_BACKEND=local`,
> `SCHEDULER_BACKEND=loop`, `SECRETS_BACKEND=plaintext-dev`,
> `CHANNELS_ENABLED=false`). Flipping to production backends is a set of
> conscious, reversible config changes gated behind the one-time external ops
> below. **Do not treat "deployed" as "cut over."** The retire-OpenClaw
> moment is a separate, deliberate decision Charles owns (see §10).

Project: `totemic-formula-467102-s9` · Region: `us-central1` · Service
account: `openclaw-adk@totemic-formula-467102-s9.iam.gserviceaccount.com` ·
Cloud SQL: `totemic-formula-467102-s9:us-central1:quill-datasite-db`.

Legend for **Status**: `LIVE` = already active on defaults · `STAGED` =
code-complete, one-time external op + config flip to activate · `EXTERNAL` =
requires a human action on a third-party console (Google/Telegram) that
cannot be scripted.

---

## 0. Pre-flight — what is already live vs. staged

| Capability | Default backend | Prod backend | Status | §  |
|---|---|---|---|---|
| Model provider | `anthropic` (ANTHROPIC_API_KEY) | `vertex` (when quota lands) | LIVE (anthropic) | §1 |
| Memory embeddings | keyword fallback | `gemini` (GEMINI_API_KEY) | STAGED | §2 |
| pgvector extension | degraded (no vectors) | `CREATE EXTENSION vector` | STAGED | §2 |
| Event bus | `inline` | `pubsub` | STAGED | §3 |
| Sub-agent jobs | `local` | `cloudrun` | STAGED | §4 |
| Scheduler | `loop` | `cloudscheduler` | STAGED | §5 |
| Tenant secrets | `plaintext-dev` | `kms` | STAGED | §6 |
| Telegram channel | disabled | webhook + BotFather token | EXTERNAL | §7 |
| Google Chat channel | disabled | Marketplace verification | EXTERNAL | §8 |
| Channels master gate | `CHANNELS_ENABLED=false` | `true` | STAGED | §9 |

**Rule of thumb:** you can deploy the current image to prod today and it will
serve web chat, the Agent Builder, budgets/meters, and approvals correctly on
all-default backends. Everything below *upgrades* a subsystem from its safe
default to its production backend. Do them in this order; each is independent
and reversible (flip the flag back).

---

## 1. Model provider — GEMINI_API_KEY rotation + Vertex

- **Why external:** API keys live in Secret Manager, never in the repo. The
  Vertex path is gated on a Google-side quota increase (project quota = 0
  today; see `SPIKE_FINDINGS.md`).
- **Current status:** Anthropic-direct is the **live** path
  (`MODEL_PROVIDER=anthropic`, `ANTHROPIC_API_KEY`). Fully functional.
- **GEMINI_API_KEY:** rotated 2026-07-06 after the prior key was reported
  leaked (KNOWN_ISSUES A2 #1). The deploy workflow injects
  `GEMINI_API_KEY=GEMINI_API_KEY:latest`. **Verify it is the rotated value:**

  ```bash
  gcloud secrets versions list GEMINI_API_KEY \
    --project totemic-formula-467102-s9 | head -3
  # confirm the newest ENABLED version is dated >= 2026-07-06
  ```

- **Vertex cutover (optional, later):** when the Vertex Claude/embeddings
  quota increase lands, flip `MODEL_PROVIDER=vertex` /
  `EMBEDDING_PROVIDER=vertex`. Both fail cleanly with a quota-hint error
  until then, so a premature flip is safe (degrades, doesn't break).

**Activates:** `MODEL_PROVIDER`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`,
`EMBEDDING_PROVIDER`.

---

## 2. Memory: pgvector extension + Gemini embeddings

- **Why external:** pgvector is not a "trusted" extension; the app's
  DATABASE_URL role cannot `CREATE EXTENSION vector` on vanilla Postgres
  (KNOWN_ISSUES A2 #2). A privileged role must create it once.
- **Current status:** memory **works today** in degraded mode — memories save
  without vectors and `memory_search` uses keyword (ILIKE) fallback. No data
  loss; self-heals once the extension + embeddings are on.

One-time, as the Cloud SQL `postgres`/`cloudsqlsuperuser` role:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Then the **next deploy's migrations** conditionally add the `embedding
vector(768)` column + HNSW index automatically (they are guarded on the
extension existing — no manual DDL needed).

- **Embeddings on:** set `EMBEDDING_PROVIDER=gemini` (deploy workflow already
  does this). Rows saved while degraded stay un-embedded; a backfill is
  additive later if wanted.

**Activates:** `EMBEDDING_PROVIDER=gemini`, `GEMINI_API_KEY` (§1), the
`vector` extension.

---

## 3. Event bus — Pub/Sub topics + dead-letter (`EVENT_BUS=pubsub`)

- **Why external:** app code never creates Pub/Sub resources. Every event is
  **already written durably** to `agentcloud_events` (replayable) regardless
  of backend; `pubsub` only adds best-effort fan-out. A publish failure can
  never fail a user turn.
- **Current status:** `EVENT_BUS=inline` (LIVE) — durable rows, no external
  fan-out. Fully functional for the platform's own needs.

One-time (EVENTS.md contract — dead-letter after 5 delivery attempts):

```bash
gcloud pubsub topics create agentcloud-events \
  --project totemic-formula-467102-s9
gcloud pubsub topics create agentcloud-events-deadletter \
  --project totemic-formula-467102-s9
gcloud pubsub subscriptions create agentcloud-events-sub \
  --project totemic-formula-467102-s9 \
  --topic agentcloud-events \
  --dead-letter-topic agentcloud-events-deadletter \
  --max-delivery-attempts 5
# grant the DLQ publish + subscription ack perms to the SA:
gcloud pubsub topics add-iam-policy-binding agentcloud-events-deadletter \
  --project totemic-formula-467102-s9 \
  --member serviceAccount:openclaw-adk@totemic-formula-467102-s9.iam.gserviceaccount.com \
  --role roles/pubsub.publisher
```

Then deploy with `EVENT_BUS=pubsub`.

**Activates:** `EVENT_BUS=pubsub`. Reversible: flip back to `inline`.

---

## 4. Sub-agent jobs — Cloud Run Job (`JOBS_BACKEND=cloudrun`)

- **Why external:** app code never creates a Cloud Run Job or grants
  `run.jobs.run`. The `local` backend is **not durable** across instance
  recycles (KNOWN_ISSUES A3 #2), so prod sub-agents should use `cloudrun`.
- **Current status:** `JOBS_BACKEND=local` (LIVE) — in-process asyncio task;
  fine for dev/single-instance, loses queued jobs on restart.

One-time (this same image; CI keeps it fresh):

```bash
gcloud run jobs create agentcloud-subagent \
  --image gcr.io/totemic-formula-467102-s9/quill-agent-orchestrator:<sha> \
  --region us-central1 --project totemic-formula-467102-s9 \
  --service-account openclaw-adk@totemic-formula-467102-s9.iam.gserviceaccount.com \
  --set-cloudsql-instances totemic-formula-467102-s9:us-central1:quill-datasite-db \
  --set-secrets DATABASE_URL=QUILL_DATABASE_URL:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,QUILL_AGENT_SECRET=QUILL_AGENT_SECRET:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest \
  --command python --args -m,app.jobs,run
# grant the orchestrator SA permission to launch job executions:
gcloud run jobs add-iam-policy-binding agentcloud-subagent \
  --region us-central1 --project totemic-formula-467102-s9 \
  --member serviceAccount:openclaw-adk@totemic-formula-467102-s9.iam.gserviceaccount.com \
  --role roles/run.invoker
```

Then deploy the service with `JOBS_BACKEND=cloudrun` +
`CLOUDRUN_JOB_NAME=agentcloud-subagent`.

**Activates:** `JOBS_BACKEND=cloudrun`, `CLOUDRUN_JOB_NAME`. Reversible.

---

## 5. Scheduler — Cloud Scheduler tick (`SCHEDULER_BACKEND=cloudscheduler`)

- **Why external:** app code never creates a Cloud Scheduler job. The `loop`
  backend needs a live instance to tick (KNOWN_ISSUES A4 #3) — with
  scale-to-zero, due schedules wait for the next request. `cloudscheduler`
  lets Cloud Run scale to zero between ticks.
- **Current status:** `SCHEDULER_BACKEND=loop` (LIVE). Safe on multiple
  instances (SKIP LOCKED claim never double-fires), but **on Cloud Run
  either set `min-instances=1` OR switch to `cloudscheduler`.**

One-time:

```bash
# shared secret (also set SCHEDULER_TICK_SECRET on the service deploy):
gcloud secrets create AGENTCLOUD_SCHEDULER_TICK_SECRET \
  --project totemic-formula-467102-s9
# ... add a version with the secret value ...
gcloud scheduler jobs create http agentcloud-scheduler-tick \
  --project totemic-formula-467102-s9 --location us-central1 \
  --schedule "* * * * *" \
  --uri https://<service-url>/v1/internal/scheduler/tick \
  --http-method POST \
  --headers X-Agent-Secret=<the-secret> \
  --oidc-service-account-email openclaw-adk@totemic-formula-467102-s9.iam.gserviceaccount.com
```

Defense-in-depth: OIDC/IAM gates ingress **and** the `X-Agent-Secret` header
is verified in-app. The endpoint is **disabled while the secret is unset**
(returns 403), so it cannot be triggered before you're ready.

**Activates:** `SCHEDULER_BACKEND=cloudscheduler`, `SCHEDULER_TICK_SECRET`.
Reversible: `loop` + `min-instances=1`.

---

## 6. Tenant secrets — KMS envelope (`SECRETS_BACKEND=kms`)

- **Why external:** app code never creates a KMS keyring/key or grants
  crypto IAM.
- **Current status:** `SECRETS_BACKEND=plaintext-dev` (LIVE, **dev only**).
  ⚠️ **`plaintext-dev` stores secret values UNENCRYPTED** (KNOWN_ISSUES B2 #4
  — the name is deliberately alarming). **Never leave `plaintext-dev`
  selected in a promoted environment.** There is no auto re-encryption sweep;
  set `kms` before any real tenant secret is stored.

One-time (SECRETS.md §6):

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
```

Then deploy with:

```
SECRETS_BACKEND=kms
SECRETS_KMS_KEY=projects/totemic-formula-467102-s9/locations/us-central1/keyRings/agentcloud/cryptoKeys/tenant-secrets
```

**Activates:** `SECRETS_BACKEND=kms`, `SECRETS_KMS_KEY`.

---

## 7. Telegram channel — BotFather + setWebhook (EXTERNAL)

- **Why external:** creating a bot and registering its webhook are Telegram
  operations outside GCP and the codebase (KNOWN_ISSUES D #2). The adapter,
  webhook handler, secret verification, and pairing flow are complete +
  unit-tested; until `setWebhook` is called, inbound updates never arrive.

**Charles must do (Telegram side):**

1. In Telegram, message **@BotFather** → `/newbot` → follow prompts → copy
   the **bot token**. Store it:
   ```bash
   printf '%s' '<bot-token>' | gcloud secrets create AGENTCLOUD_TELEGRAM_BOT_TOKEN \
     --project totemic-formula-467102-s9 --data-file=-
   ```
2. Choose a webhook secret (any high-entropy string) and store it as
   `AGENTCLOUD_TELEGRAM_WEBHOOK_SECRET`.
3. Register the webhook (after the service is deployed with the token +
   secret env, and `CHANNELS_ENABLED=true` — §9):
   ```bash
   curl -sS "https://api.telegram.org/bot<bot-token>/setWebhook" \
     -d "url=https://<service-url>/v1/channels/telegram/webhook" \
     -d "secret_token=<the-webhook-secret>"
   # expect {"ok":true,"result":true,...}
   ```

**Activates:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` (+ §9).

---

## 8. Google Chat channel — Marketplace verification (EXTERNAL)

- **Why external:** a Google Chat app must be published/verified in the
  Google Workspace Marketplace with the webhook URL + verification token
  configured on Google's side (KNOWN_ISSUES D #1). This is a Google console
  workflow that cannot be scripted. The adapter/webhook/token
  verification/pairing/synchronous reply are complete + unit-tested.

**Charles must do (Google side):**

1. Google Cloud Console → **Google Chat API** → *Configuration*: set app
   name/avatar, **App URL** =
   `https://<service-url>/v1/channels/googlechat/webhook`, connection type =
   *App URL (HTTP endpoint)*.
2. Copy the **verification token** Google shows and store it:
   ```bash
   printf '%s' '<verification-token>' | gcloud secrets create \
     AGENTCLOUD_GOOGLECHAT_VERIFICATION_TOKEN \
     --project totemic-formula-467102-s9 --data-file=-
   ```
3. For org-wide availability, submit the app for **Google Workspace
   Marketplace** listing/verification. (For internal-only use, restrict
   visibility to your domain — verification is lighter.)

**Activates:** `GOOGLECHAT_VERIFICATION_TOKEN` (+ SA) (+ §9).

---

## 9. Channels master gate (`CHANNELS_ENABLED=true`)

- **Why staged:** `CHANNELS_ENABLED=false` by default (KNOWN_ISSUES D #4) so
  no half-configured channel accepts traffic. Every webhook + bridge channel
  route returns 503 until this is `true` **and** the per-platform secrets are
  present (an adapter whose secret is unset 503s individually).
- **Flip only after §7 and/or §8** are done for the platform(s) you want:

  ```
  CHANNELS_ENABLED=true
  ```

**Activates:** all channel webhooks + `/v1/agent-cloud/channels/*` bridge
routes. Reversible: flip back to `false` to instantly dark all channels.

---

## 10. Per-service env / secret matrix

The one deployable image (`quill-agent-orchestrator`) runs as three GCP
surfaces. Here is the full env/secret matrix per surface.

### Cloud Run **service** (the orchestrator API)

| Env / secret | Source | Default | Notes |
|---|---|---|---|
| `DATABASE_URL` | secret `QUILL_DATABASE_URL` | — | required |
| `ANTHROPIC_API_KEY` | secret | — | required (live model path) |
| `GEMINI_API_KEY` | secret | — | §2 embeddings |
| `QUILL_AGENT_SECRET` | secret | — | Quill read/write tools + reconcile sweep |
| `MODEL_PROVIDER` | env | `anthropic` | §1 |
| `EMBEDDING_PROVIDER` | env | `gemini` (CI) | §2 |
| `EVENT_BUS` | env | `inline` | §3 |
| `JOBS_BACKEND` | env | `local` | §4 |
| `CLOUDRUN_JOB_NAME` | env | — | §4 (when `cloudrun`) |
| `SCHEDULER_BACKEND` | env | `loop` | §5 |
| `SCHEDULER_TICK_SECRET` | secret | — | §5 (enables tick endpoint) |
| `SECRETS_BACKEND` | env | `plaintext-dev` | §6 — **set `kms` in prod** |
| `SECRETS_KMS_KEY` | env | — | §6 (when `kms`) |
| `CHANNELS_ENABLED` | env | `false` | §9 |
| `TELEGRAM_BOT_TOKEN` | secret | — | §7 |
| `TELEGRAM_WEBHOOK_SECRET` | secret | — | §7 |
| `GOOGLECHAT_VERIFICATION_TOKEN` | secret | — | §8 |
| `APPROVALS_NOTIFY_SECRET` | secret | — | A6 best-effort resolution push |
| `AGENTCLOUD_TENANT_ID` | env | `quill-main` | org tenant id |
| `TENANT_BUDGET_DEFAULT_USD` | env | `10.0` | LIMITS.md §1 |
| `ORG_TENANT_BUDGET_USD` | env | `100.0` | LIMITS.md §1 |
| `RATE_LIMIT_PER_MIN` | env | `30` | LIMITS.md §3 |
| `RATE_LIMIT_JOBS_PER_MIN` | env | `10` | LIMITS.md §3 |

### Cloud Run **Job: `agentcloud-subagent`** (§4)

Same image + `DATABASE_URL`, `ANTHROPIC_API_KEY`, `QUILL_AGENT_SECRET`,
`GEMINI_API_KEY`; `--command python --args -m,app.jobs,run`; `JOB_ID` /
`JOB_TENANT_ID` are set per execution by the launcher.

### Cloud Run **Job: `agentcloud-admin`** (maintenance, one-time create)

Same image + `DATABASE_URL`; `--command python --args -m,app.admin,rls-probe`
as the default; per run `gcloud run jobs execute agentcloud-admin --args -m,app.admin,<subcommand>`.

### The Quill **api** bridge (already deployed as part of Quill)

Reaches agent-cloud over the network at `AGENTCLOUD_URL`. Bridge auth is the
normal Quill JWT; **agent-cloud must not be exposed publicly except via the
bridge** (KNOWN_ISSUES A5 #3 — Cloud Run ingress/IAM). Env:
`AGENTCLOUD_URL`, `AGENTCLOUD_TENANT_ID`,
`AGENTCLOUD_PROVISION_TIMEOUT_SECONDS`, `AGENTCLOUD_TIMEOUT_SECONDS`.

---

## 11. Health check reminder

External health checks must hit **`GET /health`**, not `/healthz` — Google's
frontend intercepts the literal `/healthz` on `*.run.app` and returns its own
404 before the request reaches the container (README "Health checks";
KNOWN_ISSUES A1). `/healthz` stays registered for container-internal probes
only.

---

## 12. Dogfood — provision Charles as tenant #1

See `scripts/dogfood_seed.py` (run via the agent-cloud venv) and its
one-command recipe. It provisions Charles's personal tenant + a real working
agent, idempotently, and supports `--dry-run`. **Do not run against prod
live in this sprint** — the parent (Axe main) runs it as a deliberate step.

```bash
# dry-run (prints the plan, no writes) — safe anywhere:
.venv/bin/python -m scripts.dogfood_seed --tenant user-charles --dry-run

# real (local/sqlite or prod, run consciously):
.venv/bin/python -m scripts.dogfood_seed --tenant user-charles
```

Details + the full parity story: `MIGRATION.md`.

---

## 13. Go-live decision (Charles owns this)

The platform being *deployed and healthy* is **not** the same as *cutting
over*. Retiring OpenClaw as Charles's brain is a deliberate moment:

1. Complete §1–§9 for the subsystems you want in prod backends.
2. Run the dogfood seed (§12) to make Charles tenant #1 with a working agent.
3. Live-test the canonical paths: web chat, a scheduled reminder, a sub-agent
   job, an approval-gated write, a paired channel message.
4. Run in parallel with OpenClaw for a soak period (dogfood → limited → full,
   see `MIGRATION.md`).
5. **Only then** decide to retire OpenClaw. **Nothing in this codebase flips
   that switch — it is yours to pull.**
