# agent-cloud — Known Issues

Severity legend: (invisible) internal only · (visible-tolerable) noticeable,
nothing breaks · (visible-frustrating) users hit it early · (blocking).

## A4 (scheduler)

1. **Tick cadence bounds firing precision.** Schedules fire on the first
   tick at/after `next_run_at`: up to `SCHEDULER_TICK_SECONDS` (30s) late on
   the loop backend, up to ~60s late on the Cloud Scheduler backend. Cron
   expressions are minute-granularity anyway; do not promise second-level
   reminders. *(visible-tolerable — inherent to tick-based scheduling.)*

2. **A failed one-shot is parked, not retried.** `next_run_at` is cleared at
   claim time (that's what makes the claim atomic), so if the fire then
   fails (e.g. agent deleted/disabled, dispatch error) the row keeps
   `last_status='error: …'` + a `schedule.failed` event but will not re-fire
   on its own — PATCH `run_at` (or `enabled`) to reschedule. Cron schedules
   self-heal: the next occurrence was already computed at claim.
   *(visible-tolerable — the failure is visible on the row and in events.)*

3. **`loop` backend requires a running instance.** With
   `SCHEDULER_BACKEND=loop` on Cloud Run, an instance must be alive for
   ticks to happen — with scale-to-zero and no traffic, due schedules wait
   until the next request wakes an instance. Set min-instances=1 or switch
   to `cloudscheduler` (README has the one-time gcloud setup; not created by
   app code, hence unexercised live — the endpoint itself is unit-tested).
   *(visible-frustrating if deployed scale-to-zero with loop backend — use
   min-instances=1 or the cloudscheduler backend in prod.)*

4. **Reminder delivery is the passive A3 wake.** The fired turn's reply
   lands in the target session as a `[system wake]` message; nothing pushes
   it to an external channel yet (web-chat/channel adapters are a later
   Phase A slice). *(visible-tolerable — documented reminder semantics.)*

5. **DST edge on cron schedules.** croniter resolves wall-clock times that
   are skipped/repeated by DST transitions to the standard interpretation
   (a 2:30am schedule on spring-forward day fires at the next valid time).
   *(invisible — standard cron behavior.)*

## A3 (events + sub-agent jobs)

1. **`pubsub`/`cloudrun` backends are config-gated and unit-tested against
   mocked clients, not exercised live.** Defaults ship safe (`EVENT_BUS=inline`,
   `JOBS_BACKEND=local`). Going live needs ops-side resources: Pub/Sub topics
   `agentcloud-events` + `agentcloud-events-deadletter` and a subscription
   with the dead-letter/retry policy from EVENTS.md; a `agentcloud-subagent`
   Cloud Run Job (this image, `--command python --args -m,app.jobs,run`, same
   secrets) and `run.jobs.run` IAM for the orchestrator's service account.
   *(invisible — inline/local paths are fully functional; flip config after
   the one-time ops setup.)*

2. **`local` jobs backend is not durable across restarts.** A queued/running
   job dies with the process (Cloud Run instance recycle) and stays `queued`/
   `running` forever; there is no reaper/`timeout` sweeper yet (the `timeout`
   status exists in the contract but nothing sets it). Acceptable for dev;
   prod sub-agents should use `cloudrun`. *(visible-tolerable — a stuck job is
   visible in GET status; re-submit the task.)*

3. **Parent wake is passive (Phase A).** Completion inserts the `[system
   wake]` message into the parent session, but nothing re-invokes the parent
   agent — it sees the wake on its next turn. Proactive re-invocation is the
   Pub/Sub-consumer slice of a later sprint. *(visible-tolerable — documented
   in EVENTS.md.)*

4. **Cloud Run Job executions are fire-and-forget from the API's view.** If
   the execution fails to start (quota, IAM), the job row stays `queued` with
   no error surfaced on it; the launch error is only in the orchestrator's
   logs. *(visible-tolerable — GET shows a never-starting job; ops checks
   logs.)*

## A2 (memory subsystem)

1. **Live Gemini embeddings unverified — env `GEMINI_API_KEY` reported leaked.**
   During A2 verification the key present in the dev environment returned
   `403 PERMISSION_DENIED: "Your API key was reported as leaked. Please use
   another API key."` from the Gemini API. **A3 update:** the key was rotated
   (2026-07-06) and the deploy workflow now injects
   `GEMINI_API_KEY=GEMINI_API_KEY:latest` + `EMBEDDING_PROVIDER=gemini`, so
   semantic embeddings go live on the next deploy. Until that deploy the
   memory subsystem runs in its designed degraded mode: memories save without
   embeddings and `memory_search` uses keyword (ILIKE) fallback.
   *(visible-tolerable — self-heals on next deploy. Rows saved while degraded
   stay un-embedded; a backfill can be added later if needed.)*

2. **`CREATE EXTENSION vector` needs a privileged role on vanilla Postgres.**
   pgvector is not a "trusted" extension, so the app role can't create it on
   a plain Postgres (verified locally: `permission denied to create extension
   "vector"`; migrations catch this and degrade cleanly with a NOTICE). On
   Cloud SQL the `postgres`/`cloudsqlsuperuser` user can create it; if the
   app's DATABASE_URL role can't, run once as an admin:
   `CREATE EXTENSION IF NOT EXISTS vector;` — the next deploy's migrations
   then add the `embedding` column + HNSW index automatically (they're
   conditional on the extension existing). *(invisible once done; one-time op)*

3. **Vector dimension is fixed at table-creation time.** `EMBEDDING_DIM`
   (default 768) must match the `vector(768)` column. Changing embedding
   models to a different dimensionality requires a manual column migration +
   re-embedding. *(invisible — config discipline)*

4. **Vertex embeddings path is config-gated but unexercised** (same status as
   the Vertex Claude provider — project quota 0, SPIKE_FINDINGS.md). It fails
   with a clean named error incl. a quota hint. *(invisible)*

## A1 (carried forward)

- `/healthz` on `*.run.app` is intercepted by Google's frontend — external
  health checks must use `/health` (see README). *(visible-tolerable, ops-only)*
- Vertex Claude provider blocked on quota increase; Anthropic-direct is the
  live path. *(invisible — config cutover when quota lands)*
