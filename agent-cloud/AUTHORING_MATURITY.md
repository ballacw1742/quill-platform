# AUTHORING_MATURITY.md — Agent versioning / diff / rollback / publish (Phase 5)

Phase 5 (GAP_ASSESSMENT_S9.md §5 Phase 5, §2 9.1 "(b) Harden") productizes the
**authoring maturity** the §9.1 vision expects: an agent's definition should
evolve like a versioned document — every edit snapshotted, diffable against any
prior state, rollback-able (non-destructively), and optionally shareable/
publishable within a tenant. This document is the **canonical contract** for
the version history API, the field-level diff, the rollback op, and the
publish/share flag. All code — agent-cloud CRUD, the api bridge, the web UI,
and every test — uses exactly these shapes. Do not invent fields outside this
document; extend it here first.

It builds on and does not change `AGENT_BUILDER.md` (the CRUD surface, seed
protection, validation, tool palette, templates), `TENANCY.md`, `EVENTS.md`,
`APPROVALS.md`, and `LIMITS.md`.

---

## 1. Data model (additive only)

### 1.1 `AgentDef.version` (new column, additive)

`agentcloud_agents` gains one column:

| field | type | notes |
|---|---|---|
| `version` | int | monotonically increasing, starts at 1 on create, `+1` on every mutating `update_agent`/`rollback`. Never decreases. |

The current row is always the *live* definition at `version`. Prior states live
as immutable rows in `agentcloud_agent_versions` (§1.2).

### 1.2 `agentcloud_agent_versions` (new table, immutable snapshots)

Each row is a frozen snapshot of an agent definition **as it was at the moment a
new version superseded it** (i.e. we snapshot the *prior* state on every update).
Tenant-scoped and RLS'd like every `agentcloud_*` table. Never mutated after
insert; never hard-deleted (audit/history, mirrors AGENT_BUILDER.md §2
soft-delete philosophy).

| field | type | notes |
|---|---|---|
| `version_row_id` | uuid (PK) | server-set |
| `tenant_id` | text | RLS key |
| `agent_id` | text | the agent this snapshot belongs to |
| `version` | int | the version number this snapshot captures |
| `system_prompt` | text | snapshotted field |
| `model` | text | snapshotted field |
| `tools` | json[] | snapshotted field |
| `memory_policy` | text | snapshotted field |
| `budget_monthly_usd` | numeric | snapshotted field |
| `enabled` | bool | snapshotted field |
| `change_action` | text | `created` \| `updated` \| `rolledback` — what produced this snapshot's *successor* |
| `changed_fields` | json[] | field names that changed relative to the prior version (`["*"]` for the initial create snapshot) |
| `rolled_back_from` | int \| null | when `change_action="rolledback"`, the version number the live row was rolled back **to** |
| `created_at` | timestamptz | when the snapshot was frozen |

Unique index on `(tenant_id, agent_id, version)` — one snapshot per version.

**Snapshot timing (important):** on `update_agent`, we (1) freeze the *current*
row's state into a version row tagged with its *current* `version`, then (2)
apply the patch and bump `AgentDef.version`. So `agentcloud_agent_versions`
always holds every superseded state; the live `AgentDef` holds the newest. The
newest version is therefore NOT in the versions table until it is itself
superseded — the list endpoint (§2.1) synthesizes the live row as the head.

---

## 2. API (agent-cloud, tenant-scoped, `{items}`/`{detail}` envelopes)

All are tenant-scoped exactly like AGENT_BUILDER.md §2: every query filters
`tenant_id` at the app layer AND runs inside `tenant_session()` (RLS second
belt). Cross-tenant ids are 404-not-403 (TENANCY.md §4). Errors use the standard
`{"detail": "..."}` envelope.

### 2.1 `GET /v1/agents/{agent_id}/versions?tenant_id=…` — list history

Newest-first list of every version (the live head + all snapshots). List
envelope `{items, total, limit, offset}` (LESSONS #1 default).

```jsonc
{
  "items": [
    { "version": 3, "change_action": "rolledback", "changed_fields": ["system_prompt","tools"],
      "rolled_back_from": 1, "is_current": true,  "created_at": "…" },
    { "version": 2, "change_action": "updated",    "changed_fields": ["model"],
      "rolled_back_from": null, "is_current": false, "created_at": "…" },
    { "version": 1, "change_action": "created",    "changed_fields": ["*"],
      "rolled_back_from": null, "is_current": false, "created_at": "…" }
  ],
  "total": 3, "limit": 100, "offset": 0
}
```

The **current** version (`is_current:true`) is the live `AgentDef` row; it has no
frozen snapshot yet (see §1.2) so its `change_action`/`changed_fields`/
`rolled_back_from` are read from the most recent snapshot's *successor* metadata
that the live row carries — concretely the api records, on the live row, the
metadata of the change that produced it. To keep the model additive (no extra
columns on `AgentDef`), the list endpoint reports the current head using the
*latest snapshot's* forward metadata when present, else `{created, ["*"], null}`
for a never-updated agent. See §5 for the exact synthesis rule.

- 200 list; 404 unknown/cross-tenant agent.

### 2.2 `GET /v1/agents/{agent_id}/versions/{version}?tenant_id=…` — one version detail

Full field snapshot of a single version (the definition as it was at that
version). For the current version, returns the live row's fields.

```jsonc
{
  "agent_id": "research", "version": 2,
  "system_prompt": "…", "model": "claude-fable-5",
  "tools": ["get_time"], "memory_policy": "off",
  "budget_monthly_usd": 10.0, "enabled": true,
  "is_current": false, "created_at": "…"
}
```

- 200 detail; 404 unknown agent OR unknown version (indistinguishable).

### 2.3 `GET /v1/agents/{agent_id}/diff?tenant_id=…&from=<int>&to=<int>` — field-level diff

Field-level diff between two versions. `from`/`to` are version numbers; either
may be the current version. Only fields that differ appear in `changes`.

```jsonc
{
  "agent_id": "research",
  "from_version": 1, "to_version": 3,
  "changes": [
    { "field": "system_prompt", "from": "old prompt", "to": "new prompt" },
    { "field": "tools", "from": ["get_time"], "to": ["get_time","quill_finance_summary"] }
  ]
}
```

Diffed fields (fixed set): `system_prompt`, `model`, `tools`, `memory_policy`,
`budget_monthly_usd`, `enabled`. `tools` compares as ordered lists (order is
semantically meaningful — it's the offer order). `changes` is empty `[]` when
the two versions are identical.

- 200 diff; 400 if `from`/`to` missing or not ints; 404 unknown agent OR
  unknown version.

### 2.4 `POST /v1/agents/{agent_id}/rollback?tenant_id=…` — rollback to a prior version

Body: `{ "to_version": <int> }`. Restores the agent's mutable fields
(`system_prompt`, `model`, `tools`, `memory_policy`, `budget_monthly_usd`,
`enabled`) to the snapshot at `to_version`, as a **new version** (never
destructive; the prior live state is snapshotted first exactly like an update).
The new version's snapshot metadata is `change_action="rolledback"`,
`rolled_back_from=<to_version>`.

**Seed protection (AGENT_BUILDER.md §3):** rollback must not leave a seed
`enabled=false`. If the target snapshot has `enabled=false` and the agent is a
seed, the `enabled` field is NOT restored (kept `true`); all other fields are
restored. (A seed can never be disabled by any path.) Response returns the new
live detail (AGENT_BUILDER.md §1 detail shape, now with `version`).

Emits an `agent.rolledback` event (§4). 200 detail; 400 missing/invalid
`to_version`; 404 unknown agent OR unknown target version.

### 2.5 Publish / share

An agent version's *current* definition can be marked shareable/publishable
within the tenant (a template other agents in the same tenant may clone). This
is a tenant-scoped visibility flag on the live agent, additive and reversible.

Rather than a new `AgentDef` column (models.py is shared this wave — see the
models caution), the publish flag is stored as a **dedicated, well-known
version-metadata row** is avoided; instead publish state is a boolean derived
from a small additive column `published` on `AgentDef`. NOTE: to keep the
shared-models diff minimal we add exactly ONE more boolean column `published`
(default false) alongside `version`. Both are additive, nullable-safe, and do
not reorder existing columns.

| method / path | body | success | errors |
|---|---|---|---|
| `POST /v1/agents/{agent_id}/publish?tenant_id=…` | `{ "published": bool }` | 200 detail | 404 unknown |

Publishing/unpublishing is allowed on any agent including seeds (it does not
disable them). It emits an `agent.published` event (§4). The agent detail shape
(AGENT_BUILDER.md §1) is extended with `version` and `published` (both additive,
backward compatible — existing consumers ignore unknown fields).

`GET /v1/agents/{agent_id}` and all CRUD responses now include `version` (int)
and `published` (bool).

### 2.6 Tenant listing of published agents

`GET /v1/agents/published?tenant_id=…` returns the tenant's published agents as
clone-source cards (same fields as a template, plus `agent_id` + `version`), so
the builder can offer "clone from a published agent in your workspace". List
envelope. Tenant-isolated (no cross-tenant leakage — a tenant only ever sees its
own published agents).

```jsonc
{ "items": [
  { "agent_id": "ops", "version": 4, "name": "ops",
    "summary": "Published agent (v4)",
    "system_prompt": "…", "model": "…", "tools": ["…"],
    "memory_policy": "…", "budget_monthly_usd": 10.0 } ],
  "total": 1, "limit": 100, "offset": 0 }
```

---

## 3. Validation & invariants

1. **Monotonic version.** `version` starts at 1 and only ever increases. A
   rollback does not reset it — it creates version N+1 whose *contents* match an
   older version.
2. **Immutable snapshots.** `agentcloud_agent_versions` rows are insert-only.
3. **Non-destructive rollback.** Rollback snapshots current state first, so the
   pre-rollback state is always recoverable (roll forward again).
4. **Seed protection preserved.** No path can leave a seed disabled; rollback to
   a disabled snapshot keeps a seed enabled (§2.4). Seeds may still be
   versioned/diffed/rolled-back/published — only the disable is blocked.
5. **Tenant isolation.** Every version read/write filters `tenant_id`; a
   cross-tenant `agent_id` or `version` is a 404. Published-agent listing is
   tenant-scoped (no cross-tenant clone source).
6. **No-op updates don't version.** An `update_agent` that changes nothing (the
   existing AGENT_BUILDER.md behavior) does not create a snapshot and does not
   bump `version` (consistent with the "no changed fields → return unchanged"
   rule).

---

## 4. Events addendum (EVENTS.md)

Two new event types, emitted best-effort (never fail the call), written durably
to `agentcloud_events` in the same tenant transaction, then published post-commit
— exactly like `agent.updated` (AGENT_BUILDER.md §9).

| type | emitted when | payload |
|---|---|---|
| `agent.rolledback` | an agent is rolled back to a prior version | `{to_version: int, new_version: int, fields: [str]}` — `fields` = the fields restored/changed by the rollback |
| `agent.published` | an agent's publish flag is toggled | `{published: bool, version: int}` |

`agent_id` on the envelope is the affected agent; `session_id` is null. Additive
— no existing consumer depends on either.

`update_agent` continues to emit `agent.updated` (unchanged) AND now snapshots
the prior state — the snapshot is a DB side effect, not a new event.

---

## 5. Current-head synthesis rule (list endpoint §2.1)

The live `AgentDef` row is the head version. Its forward metadata
(`change_action`, `changed_fields`, `rolled_back_from`) is reconstructed as:

- If the agent has ≥1 snapshot, the head's metadata = the metadata recorded on
  the snapshot that *most recently superseded a prior version* — concretely, we
  store the forward metadata of each change on the NEW snapshot we write, so the
  head reads the last write's forward metadata from a lightweight lookup. To
  avoid an extra `AgentDef` column, the head's forward metadata is derived by
  the api as: `change_action` = the action of the transition into the current
  version, which equals the `change_action` we stamped on the snapshot of
  `version-1` at the moment we created `version`. Therefore: **the snapshot row
  for version `N-1` carries the forward metadata describing the transition
  `N-1 → N`.** The head (version `N`) reads its metadata from the snapshot of
  `N-1`.
- If the agent has no snapshot (never updated since create), the head metadata
  is `{change_action: "created", changed_fields: ["*"], rolled_back_from: null}`.

This keeps the model additive (no metadata columns on `AgentDef`) while giving a
complete, honest history.

---

## 6. api bridge (`/v1/agent-cloud/agents/{agent_id}/…`) — JWT-gated

Mirrors §2 under the bridge prefix, identical conventions to the AGENT_BUILDER.md
§8 CRUD bridge: JWT (`get_current_user`), tenant derived server-side
(`workspace=personal|org`; org → owner/partner only), `{detail}`/`{items}`
passthrough, `502 {"detail": "agent service unreachable"}` on unreachable
upstream. `agent_id`/`version`/`from`/`to`/`to_version`/`published` are
path/query/body fields — never the tenant. Client-sent `tenant_id` is never a
schema field.

| bridge route | upstream |
|---|---|
| `GET  /v1/agent-cloud/agents/{agent_id}/versions` | `GET  /v1/agents/{agent_id}/versions` |
| `GET  /v1/agent-cloud/agents/{agent_id}/versions/{version}` | `GET  /v1/agents/{agent_id}/versions/{version}` |
| `GET  /v1/agent-cloud/agents/{agent_id}/diff?from=&to=` | `GET  /v1/agents/{agent_id}/diff?from=&to=` |
| `POST /v1/agent-cloud/agents/{agent_id}/rollback` | `POST /v1/agents/{agent_id}/rollback` |
| `POST /v1/agent-cloud/agents/{agent_id}/publish` | `POST /v1/agents/{agent_id}/publish` |
| `GET  /v1/agent-cloud/agents/published` | `GET  /v1/agents/published` |

> **CROSS-SERVICE NOTE (Phase 5 build):** the api/ service is OUT OF SCOPE for
> the Phase 5 sub-agent. These six bridge routes must be added to
> `api/app/routes/agent_cloud.py` by the orchestrator (they are ~forwarders
> identical to the existing CRUD proxies using `_get_json`/`_request_json`).
> Until then, the web UI's version calls will 404 at the bridge. The web client
> is written against these exact paths so wiring is a drop-in. This is the
> LESSONS #1 contract-first surface: the shapes are fixed here so both sides
> agree.

---

## 7. Web UI

The builder (`/assistant/builder`) editor gains, for a **saved** agent
(AGENT_BUILDER.md §7 same "save to use" rule):

- A **Version history** panel: the §2.1 list, newest-first, current badged.
- A **diff view**: pick two versions → the §2.3 field-level diff rendered as a
  compact field-by-field before/after.
- A **Rollback** button per prior version → confirm → §2.4 rollback → reloads
  the editor at the new version.
- A **Publish** toggle (§2.5) with a tenant-visibility note; when on, the agent
  appears in the workspace's published-agents clone source.

`workspace=personal|org` and the JWT/tenant injection are unchanged — tenant_id
never appears client-side. Version/diff/rollback/publish reuse the same
`apiFetch`/Bearer pattern as the CRUD calls.

---

## 8. Safety invariants (carried forward)

1. Tenancy: users only see/version/diff/rollback/publish their own agents; org
   agents require owner/partner + `workspace=org`. Client-sent `tenant_id` is
   never a field.
2. Seeds cannot be disabled by any path including rollback (§2.4, §3.4).
3. History is append-only and never hard-deleted (snapshots immutable).
4. Publish is tenant-scoped visibility only — it never grants cross-tenant
   access and never changes execution/approval semantics (APPROVALS.md
   unchanged; write tools stay proposal-only + human-approved).
5. Rollback and publish do not touch the approval/proposal path, providers, or
   the api service — they are pure authoring-layer (`agentcloud_agents` +
   `agentcloud_agent_versions`) operations.
