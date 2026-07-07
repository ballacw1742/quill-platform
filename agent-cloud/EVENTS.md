# EVENTS.md — Quill Agent Cloud event contract (A3, A4 addendum)

This is the canonical contract for platform events and sub-agent wakes
(design doc §3.1 "Pub/Sub (events, wakes, completions)" and §3.4). All code
— publisher, durable audit rows, consumers, tests — uses exactly these
fields. Do not invent fields outside this document; extend it here first.

## Topics

| Topic | Purpose |
|---|---|
| `agentcloud-events` | All platform events (single topic; consumers filter on `type`). Config: `EVENT_TOPIC`. |
| `agentcloud-events-deadletter` | Dead-letter topic for undeliverable events. Config: `EVENT_DEADLETTER_TOPIC`. |

One topic, typed events. Splitting per-type topics is deferred until a
consumer needs independent throughput/ack tuning.

## Envelope (JSON, one event per Pub/Sub message)

```json
{
  "event_id":   "c1a9…-uuid4",        // globally unique; the idempotency key
  "tenant_id":  "acme",                // always present; never cross-tenant
  "agent_id":   "personal",            // "" when not agent-scoped
  "session_id": "b7f2…-uuid or null",  // session the event belongs to, if any
  "type":       "turn.completed",      // see Event types
  "ts":         "2026-07-07T12:00:00.000000+00:00",  // ISO-8601 UTC, time of emit
  "payload":    { … },                 // type-specific, see below
  "attempt":    1                      // publisher attempt counter (>=1)
}
```

Pub/Sub message attributes mirror `tenant_id` and `type` (for subscription
filters); `ordering_key` = `session_id` (or `tenant_id` when session-less)
when ordered delivery is enabled on the subscription.

## Event types & payloads

| type | emitted when | payload |
|---|---|---|
| `turn.completed` | a chat turn finishes (incl. refusals) | `{model, tool_calls: [str], input_tokens, output_tokens, cost_usd, budget_exceeded: bool}` |
| `tool.executed` | each tool call inside a turn | `{name, status: "ok"\|"denied"}` |
| `budget.exceeded` | the monthly-cap refusal fires | `{month_spend_usd, budget_monthly_usd}` |
| `subagent.started` | a job transitions queued→running | `{job_id, task_preview}` (task truncated to 200 chars) |
| `subagent.completed` | a job finishes ok | `{job_id, reply_preview, budget_exceeded: bool, cost_usd}` |
| `subagent.failed` | a job errors or times out | `{job_id, error}` |
| `schedule.fired` | a due schedule is claimed and its job is enqueued (A4) | `{schedule_id, name, kind: "at"\|"cron", job_id}` |
| `schedule.failed` | a due schedule fails to fire (e.g. unknown/disabled agent, dispatch error) | `{schedule_id, name, error}` |

`session_id` on subagent events is the **sub-agent's own session**; the
parent session is in the job row (`agentcloud_jobs.parent_session_id`).

`session_id` on schedule events is the schedule's optional **target
session** (`agentcloud_schedules.session_id` — the session the fired job
wakes on completion), or null. `schedule.fired` marks the *enqueue* of the
job; the job's own lifecycle then emits the normal `subagent.started/
completed/failed` events with the `job_id` from the `schedule.fired`
payload, so consumers can join the two.

## Delivery, ordering, idempotency

- **At-least-once.** Consumers MUST dedupe on `event_id` (it is also the PK
  of the durable `agentcloud_events` row — `INSERT … ON CONFLICT DO NOTHING`
  is the canonical consumer dedupe).
- **Ordering** is best-effort per `ordering_key` only; cross-session order
  is undefined. Consumers must not assume `tool.executed` arrives before its
  `turn.completed`.
- **`attempt`** increments on publisher-side retries of the same
  `event_id`; consumers treat any attempt of an event_id as the same event.

## Durability: `agentcloud_events` table

Every emitted event is also written as a row in `agentcloud_events`
(tenant-namespaced, RLS'd like every `agentcloud_*` table) inside the same
tx2 that persists the turn/job state. The table is the audit/replay source
of truth; the bus is the notification path. Column ↔ envelope mapping is
1:1 (`created_at` = `ts`).

**Publish is best-effort and never blocks or fails a user turn**: the DB row
commits first; a bus publish failure is logged (`agentcloud.events`) and the
event remains replayable from the table.

## Dead-letter policy

The Pub/Sub subscription(s) (created ops-side, not by app code) must be
configured with:

- `--dead-letter-topic=agentcloud-events-deadletter`
- `--max-delivery-attempts=5`
- retry policy: exponential backoff, `--min-retry-delay=10s --max-retry-delay=600s`

Dead-lettered messages are inspected/replayed manually; because every event
also exists in `agentcloud_events`, a dead-lettered message can always be
reconciled against the durable row by `event_id`.

## Buses (`EVENT_BUS` config, gated like MODEL_PROVIDER)

- `inline` (default; local/dev/tests): in-process dispatch to registered
  subscribers, synchronous, no network. Same envelope.
- `pubsub`: `google-cloud-pubsub` publisher to `EVENT_TOPIC` in
  `PUBSUB_PROJECT`. Publisher errors are caught + logged; a turn never fails
  because of the bus.

## Sub-agent jobs & the parent-session wake

`agentcloud_jobs` (RLS'd): `job_id, tenant_id, agent_id, parent_session_id?,
session_id?` (the sub-agent's own session, set at run start), `task, status
queued|running|ok|error|timeout, payload JSONB, result JSONB, error,
created_at, started_at, finished_at`.

Lifecycle: `POST /v1/agents/subagents` inserts the row (`queued`) and
dispatches per `JOBS_BACKEND` (`local` = in-process asyncio task; `cloudrun`
= Cloud Run Job execution running `python -m app.jobs run <job_id>`). The
runner: marks `running` + emits `subagent.started` → runs a normal orchestrator
turn (same budget rows, same refusal semantics) in a fresh sub-session →
persists `result` (`{reply, session_id, usage, budget_exceeded}`) + emits
`subagent.completed` / `subagent.failed`.

**Wake:** if `parent_session_id` is set, completion inserts one message into
the parent session with `role="user"` and content:

```json
[{"type": "text", "text": "[system wake] Sub-agent job <job_id> (agent <agent_id>) <completed|failed>.\nTask: <task_preview>\nResult: <reply or error>"}]
```

`role="user"` (not a new role) because session history is replayed verbatim
to the model provider, which only accepts user/assistant roles. The
`[system wake]` prefix is the documented marker. The wake is written in the
same tx that finalizes the job row, so a committed job always has its wake
(and vice versa). The parent session's `updated_at` is touched; the parent
agent sees the wake as context on its next turn (Phase A — proactive
re-invocation of the parent is a later slice).

Wake idempotency: the wake insert happens exactly once because it shares the
job-finalization transaction (status transition running→ok/error is the
guard; a re-run of a finalized job is a no-op).
