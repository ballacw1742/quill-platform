# APPROVALS.md — Agent-proposed writes through the Quill HITL queue (A6)

Sprint A6 closes Phase A: agents can now *propose* Quill writes, but every
write lands in the existing Quill `/queue` approval system
(`api/app/routes/approvals.py` + `api/app/services/approvals.py`) and only
executes after a human approves. The agent secret still authorizes **zero
direct writes** to Quill business objects — the only thing an agent can
create with `X-Agent-Secret` is an *approval item* (that endpoint has always
been agent-facing), and the only thing that executes it is the existing
api-side approvals executor, exactly like `site_advance.create_project`.

```
model → write tool → validate args
      → POST /v1/approvals (X-Agent-Secret, workflow=agentcloud.<action>)
      → agentcloud_proposals row (status=pending)
      → tool returns {"status": "pending_approval", ...} to the model
...human decides in Quill /queue...
      → api executor runs the action inside execute_approval (approve)
      → api best-effort notifies agent-cloud (POST /v1/internal/approvals/notify)
      → agent-cloud finalizes the proposal + emits approval.resolved
        + inserts a [system wake] message into the originating session
      → (belt #2) the A4 scheduler tick reconciles stale pending proposals by
        polling GET /v1/approvals/{id} with the agent secret
```

## 1. Write-tool catalog (`app/tools/quill_writes.py`)

All five tools are **proposal-only**: they never mutate Quill directly. Each
maps 1:1 to a workflow type `agentcloud.<suffix>` executed api-side. Args are
validated *before* queueing (agent-cloud) and *again* before executing (api).

| Tool | Workflow | Executes (api-side) |
|---|---|---|
| `quill_project_update` | `agentcloud.project_update` | `Project` phase/status/notes update; `advance_phase=true` steps `PHASE_ORDER`; explicit `phase`/`status` must be in `VALID_PHASES`/`VALID_STATUSES` |
| `quill_project_log_note` | `agentcloud.project_log_note` | insert `ProjectLogEntry` (`entry_type` ∈ `VALID_ENTRY_TYPES`: general/issue/milestone/decision) |
| `quill_project_milestone_create` | `agentcloud.project_milestone_create` | insert `ProjectMilestone` (name, description?, due_date? ISO date) |
| `quill_deal_update` | `agentcloud.deal_update` | `Deal` update (stage ∈ `VALID_DEAL_STAGES`, value_usd, probability_pct, expected_close?, notes, lost_reason); stage→won upgrades the account to customer, same as the human PATCH route |
| `quill_request_update` | `agentcloud.request_update` | `RequestRecord` status ∈ {complete, failed} + response text, mirroring the agent-facing PATCH `/v1/requests/{id}` semantics |

Exposure: tools exist in the registry but are **not** in any seed agent's
allow-list. An operator must add them to the agent definition's `tools`
JSONB. Enforcement is the existing double belt (`specs_for_allowlist` +
`run_tool` re-check).

## 2. Proposed-action JSON schema (payload.proposed_action)

Every queue item carries this normalized shape in `payload.proposed_action`:

```json
{
  "kind": "agentcloud_write",
  "action": "project_update",            // workflow suffix
  "args": { "project_id": "…", "advance_phase": true },
  "tenant_id": "charles",                 // agent-cloud tenant
  "agent_id": "quill",
  "session_id": "…uuid or null…",
  "proposal_id": "…agentcloud_proposals.id…",
  "idempotency_key": "sha256:…"
}
```

`args` per action (all unknown keys rejected at validation):

- `project_update`: `project_id` (str, req). One of: `advance_phase` (bool
  true), or any of `phase` (str), `status` (str), `notes` (str ≤ 4000).
- `project_log_note`: `project_id` (req), `entry_type` (req), `text`
  (req, ≤ 4000).
- `project_milestone_create`: `project_id` (req), `name` (req ≤ 200),
  `description?` (≤ 2000), `due_date?` (`YYYY-MM-DD`).
- `deal_update`: `deal_id` (req) + at least one of `stage`, `value_usd`
  (number ≥ 0), `probability_pct` (0–100), `expected_close`
  (`YYYY-MM-DD`), `notes` (≤ 4000), `lost_reason` (≤ 1000).
- `request_update`: `request_id` (req), `status` (req, `complete|failed`),
  `response?` (≤ 8000).

## 3. Exact queue payload (POST /v1/approvals, X-Agent-Secret)

Matches `ApprovalCreate` in `api/app/schemas.py`:

```json
{
  "agent_id": "agentcloud:<tenant>/<agent>",
  "agent_version": "a6",
  "workflow": "agentcloud.project_update",
  "lane": 2,
  "priority": "normal",
  "target_system": "none",
  "api_call": "PATCH /v1/projects/{project_id}",
  "payload": { "proposed_action": { …see §2… } },
  "agent_confidence": 0.0,
  "agent_reasoning": "<summary the tool passes through>"
}
```

Lane is always **2 (single approver)** for A6 — no auto-execute lane for
agent writes. The response's `id` is stored as
`agentcloud_proposals.quill_approval_id`.

## 4. `agentcloud_proposals` table (agent-cloud, RLS'd)

```
proposal_id       UUID PK default gen_random_uuid()
tenant_id         TEXT NOT NULL
agent_id          TEXT NOT NULL
session_id        UUID NULL            -- originating session (wake target)
tool_name         TEXT NOT NULL        -- registry tool name
action            TEXT NOT NULL        -- workflow suffix
args              JSONB NOT NULL
idempotency_key   TEXT NOT NULL        -- sha256(tenant|agent|tool|canonical args)
quill_approval_id TEXT NULL            -- api-side ApprovalItem.id
status            TEXT NOT NULL DEFAULT 'pending'
                  -- pending | executed | declined | failed | expired
result            JSONB NULL           -- {status, external_ref?, error?, source}
created_at / updated_at / resolved_at TIMESTAMPTZ
```

DDL lives in `app/migrations.py` (`DDL_A6`, single-statement idempotent
entries) and the table is appended to `_RLS_TABLES` (tenant + admin
policies, FORCE RLS).

**Idempotency (queue-time):** partial unique index

```sql
CREATE UNIQUE INDEX IF NOT EXISTS agentcloud_proposals_idem_idx
  ON agentcloud_proposals (tenant_id, idempotency_key) WHERE status = 'pending';
```

A repeat tool call with identical args while a matching proposal is still
pending returns the existing proposal ("already pending approval") instead
of enqueueing a duplicate. sqlite tests enforce the same rule app-side
(lookup-before-insert); Postgres has the index as the hard belt.

## 5. api-side executor (`app/services/agentcloud_actions.py`)

- `is_agentcloud_workflow(wf)` → `wf.startswith("agentcloud.")`.
- `execute_agentcloud_action(session, item, actor)` — called from
  `execute_approval` (same seam as site_advance): re-validates
  `payload.proposed_action` against §2 (schema + enum values), loads the
  target row, applies the mutation, returns `external_ref` (e.g.
  `project:<id>`, `deal:<id>`, `request:<id>`,
  `project_log:<id>`, `milestone:<id>`).
- Any validation/lookup error → `EXECUTION_FAILED` + `approval.execution_failed`
  audit event, identical to the site_advance failure path. Audit chain gets
  the usual `approval.executed` entry with the action + external_ref.

## 6. Resolution notify (api → agent-cloud, best-effort)

On terminal transitions of `agentcloud.*` items — **executed**,
**execution_failed**, **rejected**, **cancelled** — the api POSTs (httpx,
short timeout, failure logged and swallowed):

```
POST {AGENTCLOUD_URL}/v1/internal/approvals/notify
X-Agent-Secret: {AGENTCLOUD_NOTIFY_SECRET}
{ "approval_id": "…", "workflow": "agentcloud.…", "status": "executed",
  "external_ref": "project:…", "error": null,
  "proposal_id": "…", "tenant_id": "…" }
```

agent-cloud side: `POST /v1/internal/approvals/notify` is gated exactly like
the scheduler tick — `APPROVALS_NOTIFY_SECRET` unset ⇒ always 403. The
handler finalizes the proposal (see §8).

## 7. Reconcile sweep (belt #2, closes lost-webhook gap)

The A4 scheduler tick additionally runs `approvals.reconcile_sweep()`:
pending proposals older than `APPROVALS_RECONCILE_AFTER_SECONDS` (default
120) are polled via `GET /v1/approvals/{quill_approval_id}` with the agent
secret (read-only, already permitted). Status mapping:

| Quill ApprovalStatus | proposal status |
|---|---|
| `executed` | `executed` |
| `rejected` | `declined` |
| `execution_failed` | `failed` |
| `cancelled` / `expired` | `expired` |
| `pending` / `approved` / `suspended` / `escalated` | still open — leave pending |

Sweep errors never fail the tick (same contract as schedule firing).

## 8. Finalization (shared by notify + reconcile; race-safe)

`finalize_proposal(...)` is idempotent by construction: the status flip is a
conditional `UPDATE … WHERE status='pending'`; if no row transitions, the
call is a no-op (the other path won the race) — so notify + reconcile can
both fire and exactly one wake/event is produced. On a real transition, in
ONE tenant transaction (jobs.py wake-in-same-tx template):

1. proposal → terminal status + `result` JSONB + `resolved_at`;
2. durable `approval.resolved` event row;
3. if the proposal has a `session_id`: insert a `[system wake]` user-role
   message (approve → result summary with external_ref; decline/expire →
   polite notice) and bump `Session.updated_at`.

Then `emit()` the event (best-effort, post-commit).

## 9. Events addendum (EVENTS.md)

Two new types in `EVENT_TYPES`:

- `approval.requested` — `{proposal_id, tool, action, quill_approval_id,
  args_preview}` — emitted when a write tool queues a proposal.
- `approval.resolved` — `{proposal_id, quill_approval_id, status,
  external_ref?, error?, source: "notify"|"reconcile"}` — emitted exactly
  once on terminal transition.

## 10. Config knobs

agent-cloud (`app/config.py`):
- `APPROVALS_NOTIFY_SECRET` (default `""` ⇒ notify endpoint 403s)
- `APPROVALS_RECONCILE_AFTER_SECONDS` (default 120)
- `APPROVALS_RECONCILE_MAX_PER_TICK` (default 25)
- existing `QUILL_API_URL` / `QUILL_AGENT_SECRET` are reused for the queue
  POST and the reconcile GET.

api (`app/config.py`):
- existing `AGENTCLOUD_URL` (A5 bridge) reused as notify base URL
- `AGENTCLOUD_NOTIFY_SECRET` (default `""` ⇒ notify disabled, reconcile
  sweep still closes the loop)

## 11. Safety invariants

1. No agent-secret path can mutate Quill business objects — only create /
   cancel approval items and read.
2. Write tools are registry-present but allow-list-gated (double enforced).
3. Args validated twice (queue-time + execute-time); executor rejects
   unknown workflows and malformed proposed_action with `EXECUTION_FAILED`.
4. No double execution: api `execute_approval` is already idempotent
   (`status == EXECUTED` early-return); proposal finalization is
   conditional-update idempotent.
5. Queue-time idempotency: one pending proposal per (tenant, args-hash).
