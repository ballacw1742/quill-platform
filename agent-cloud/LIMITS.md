# LIMITS.md — tenant budgets, usage meters, rate limits (Sprint B2)

Phase B final slice (design doc §6 "Metering + abuse controls: hard
token/$ budgets per agent …, rate limits per tenant"; §7 Phase B
"budgets/meters, per-tenant secrets (KMS), rate limits"). This document is
the canonical contract for tenant-level budgets, the usage/meters API, and
per-tenant rate limits. Same rule as EVENTS.md/WEBCHAT.md: do not invent
fields outside this document — extend it here first.

Fixes KNOWN_ISSUES B1 #2: per-agent budgets alone allow N users × 2 seed
agents × $20/month of worst-case spend. The tenant-level cap bounds each
tenant regardless of how many agents it defines.

## 1. Tenant-level budgets

### Data

`agentcloud_tenants.budget_monthly_usd NUMERIC(10,2) NULL` (additive DDL).

- `NULL` (the default for every existing and newly provisioned tenant) ⇒
  the **config default** applies:
  - tenants whose id starts with `user-` (per-user personal tenants,
    TENANCY.md §1) → `TENANT_BUDGET_DEFAULT_USD` (default **$10**),
  - every other tenant (the shared org tenant `quill-main`, `smoke-…`
    environments) → `ORG_TENANT_BUDGET_USD` (default **$100**).
- A non-NULL value is an explicit per-tenant override
  (`python -m app.admin set-tenant-budget --tenant … --budget …`;
  `--budget default` clears back to NULL).

Because NULL defers to config, raising/lowering the fleet-wide default is
a config change, not a data migration.

### Enforcement (the budget gate)

A turn (chat, sub-agent job, scheduled fire — they all run through
`stream_turn`) is refused **before any model call** when EITHER:

1. the **agent's** month spend ≥ `agentcloud_agents.budget_monthly_usd`
   (the existing A1 gate, unchanged), or
2. the **tenant's total** month spend (sum over all agents) ≥ the
   effective tenant budget above.

Precedence: the agent gate is checked first; if both are exhausted the
refusal names the agent budget. Month = current UTC calendar month, same
as the A1 gate.

The refusal is the existing polite-refusal pattern: a persisted assistant
message, `budget_exceeded: true` on the result, zero model calls, never an
HTTP error. The tenant-scope refusal text names the *workspace* budget so
users don't hunt for a per-agent setting that isn't the problem.

`budget.exceeded` event payload gains a `scope` dimension — see the
EVENTS.md B2 addendum.

## 2. Usage/meters API

### agent-cloud: `GET /v1/agents/usage?tenant_id=…`

Tenant-scoped read (app-layer filter + RLS via `tenant_session()`, same
discipline as every A5 read). Current UTC calendar month. Response `200`:

```json
{
  "month": "2026-07",
  "tenant": {
    "budget_monthly_usd": 10.0,
    "budget_source": "default",        // "default" | "override"
    "spend_usd": 1.234567,
    "remaining_usd": 8.765433,          // max(0, budget - spend)
    "input_tokens": 12345,
    "output_tokens": 6789,
    "requests": 42,
    "exhausted": false
  },
  "agents": [
    {
      "agent_id": "personal",
      "budget_monthly_usd": 20.0,
      "spend_usd": 1.2,
      "remaining_usd": 18.8,
      "input_tokens": 12000,
      "output_tokens": 6000,
      "requests": 40,
      "exhausted": false
    }
  ]
}
```

- `agents` contains **every defined agent** (from `agentcloud_agents`),
  including agents with zero usage this month — the UI meter widget renders
  one meter per agent without a second call. Ordered by `agent_id`.
- Usage rows for agents that were deleted mid-month still count toward the
  tenant totals (the tenant meter is the truth for spend).
- Costs are USD floats rounded to 6 decimals (pricing-table units).
- The endpoint provisions the tenant + seed agents idempotently first
  (same path as `GET /v1/agents`) so a fresh tenant gets a well-formed
  zero-usage report.

### api bridge: `GET /v1/agent-cloud/usage?workspace=personal|org`

JWT-gated (`get_current_user`), tenant derived server-side per TENANCY.md
§1 (`workspace=org` → owner/partner only, 403 otherwise). Proxies the
agent-cloud endpoint verbatim; same error envelope + 502-unreachable
semantics as every other bridge route (WEBCHAT.md §4).

## 3. Per-tenant rate limits

### What is limited

| Bucket | Endpoints | Config | Default |
|---|---|---|---|
| `chat` | `POST /v1/agents/chat` (stream + non-stream) | `RATE_LIMIT_PER_MIN` | 30/min per tenant |
| `jobs` | `POST /v1/agents/subagents`, `POST /v1/agents/schedules` | `RATE_LIMIT_JOBS_PER_MIN` | 10/min per tenant |

`0` disables the corresponding bucket (dev/off switch). Reads are not
rate-limited in B2 (they are cheap tenant-scoped SELECTs; revisit if abuse
shows up).

### Mechanism: fixed-window counters in Postgres

`agentcloud_rate_limits(tenant_id, bucket, window_start, count)`, PK
`(tenant_id, bucket, window_start)`, RLS'd like every `agentcloud_*` table.
`window_start` is the current UTC minute boundary. Each request does one
upsert-increment (`INSERT … ON CONFLICT DO UPDATE … RETURNING count`)
inside the tenant transaction; if the returned count exceeds the limit the
request is rejected. Rows two windows old for the same (tenant, bucket)
are opportunistically deleted on the same statement path, so the table
stays O(tenants × buckets).

**Tradeoff (documented choice):** a fixed window is not a true sliding
window — a client can burst up to 2× the limit across a window boundary
(≤30 in the last second of minute N + ≤30 in the first second of N+1).
That is acceptable for an abuse-control limit and buys the simplest
mechanism that is **multi-instance-safe with existing infra**: the counter
lives in the same Postgres both orchestrator instances already share
(exactly like the SKIP LOCKED scheduler claim), needs no Redis/memorystore,
and one upsert per request is negligible next to the turn's own tx1/tx2.
In-memory windows were rejected (per-instance limits multiply by the
autoscaler); precise sliding windows (row-per-request or Redis ZSET) were
rejected as heavier with no real gain at these limits.

### Rejection shape

`429 {"detail": "rate limit exceeded: <n>/min per tenant for <bucket> — retry after <s>s"}`
with header `Retry-After: <seconds to window end>` (integer ≥ 1). On the
SSE chat path the limit is checked **before** the stream starts, so it is
a plain HTTP 429, never an SSE `error` event.

A `rate_limit.exceeded` event is recorded/published **once per
(tenant, bucket, window)** — on the first rejected request of the window,
not on every rejection — so an abusive client cannot flood the events
table. See the EVENTS.md B2 addendum.

### Config

| Setting | Where | Default | Meaning |
|---|---|---|---|
| `TENANT_BUDGET_DEFAULT_USD` | agent-cloud | `10.0` | Effective monthly budget for `user-*` tenants with NULL override. |
| `ORG_TENANT_BUDGET_USD` | agent-cloud | `100.0` | Effective monthly budget for non-`user-*` tenants with NULL override. |
| `RATE_LIMIT_PER_MIN` | agent-cloud | `30` | Chat turns per tenant per minute (0 = off). |
| `RATE_LIMIT_JOBS_PER_MIN` | agent-cloud | `10` | Sub-agent job + schedule creations per tenant per minute (0 = off). |

## 4. What B2 does NOT do

- No per-user rate limiting inside a tenant (tenant == user for personal
  workspaces anyway; the org tenant is shared by design).
- No daily/burst budget tiers; one monthly cap per level.
- No usage history endpoint (only current month); `agentcloud_usage` rows
  are per-day, so a history endpoint is additive later.
- Scheduler *fires* are not rate-limited (they are platform-initiated and
  already bounded by `SCHEDULER_MAX_PER_TICK`); only schedule *creation* is.
