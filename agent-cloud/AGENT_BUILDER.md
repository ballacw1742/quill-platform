# AGENT_BUILDER.md — Agent-definition CRUD + Agent Builder UI (Phase C)

Phase C productizes the "agent is data, not code" principle (design doc §3.3,
line 86: *"The Agent Builder in the Quill web app is a form + test console
over this row"*). Users create/edit/configure their own agents over the
`agentcloud_agents` row through the web app. This document is the **canonical
contract** for the agent-definition CRUD API, its validation rules, the tool
palette catalog, the starter templates, and the test-console shape. All code —
agent-cloud CRUD, the api bridge, the web UI, and every test — uses exactly
these shapes. Do not invent fields outside this document; extend it here first.

It builds on and does not change: `WEBCHAT.md` (read endpoints + SSE),
`TENANCY.md` (per-user tenancy, `workspace=personal|org`), `APPROVALS.md`
(write tools are approval-gated), `LIMITS.md` (budgets), `EVENTS.md` (events).

---

## 1. The agent-definition resource

An agent definition is one `agentcloud_agents` row (see `app/models.py`
`AgentDef`), tenant-scoped and RLS'd like every `agentcloud_*` table. The
CRUD surface exposes exactly these fields:

| field | type | writable | notes |
|---|---|---|---|
| `agent_id` | string (slug) | create-only | PK within tenant; immutable after create (no rename) |
| `system_prompt` | string | yes | 1..`SYSTEM_PROMPT_MAX_CHARS` (8000) |
| `model` | string (alias) | yes | must be in the allowed-model set (§4) |
| `tools` | string[] | yes | each ⊆ the registry catalog (§5); deduped, order-preserved |
| `memory_policy` | enum | yes | `off` \| `tools_only` \| `auto_recall` |
| `budget_monthly_usd` | number | yes | > 0 and ≤ the tenant budget cap (§4, LIMITS.md §1) |
| `enabled` | bool | yes | soft-disable toggle |
| `created_at` | ISO-8601 | read-only | server-set |
| `is_seed` | bool | read-only | true for `personal`/`quill` — drives seed protection (§3) |

The **read** shape returned by the CRUD endpoints is a *superset* of the A5
directory `_agent_dict` (WEBCHAT.md §3.1), adding `system_prompt`, `tools`,
and `is_seed` so the builder form can hydrate. The A5 `GET /v1/agents` list
shape is unchanged (backward compatible); the new detail read is
`GET /v1/agents/{agent_id}` (see §2).

```jsonc
// agent-definition detail (GET/POST/PATCH response)
{
  "agent_id": "research",
  "system_prompt": "You are a research assistant…",
  "model": "claude-fable-5",
  "tools": ["get_time", "quill_finance_summary"],
  "memory_policy": "tools_only",
  "budget_monthly_usd": 10.0,
  "enabled": true,
  "is_seed": false,
  "created_at": "2026-07-07T21:00:00+00:00"
}
```

---

## 2. CRUD endpoints (agent-cloud, tenant-scoped, `{detail}` envelope)

All are tenant-scoped exactly like the A5 reads: every query filters
`tenant_id` at the app layer and runs inside `tenant_session()` so RLS is the
second belt. Errors use the standard `{"detail": "..."}` envelope. Cross-tenant
ids are indistinguishable from nonexistent ids (**404-not-403**, TENANCY.md §4).

| method / path | body | success | errors |
|---|---|---|---|
| `GET /v1/agents/{agent_id}?tenant_id=…` | — | 200 detail | 404 unknown/cross-tenant |
| `POST /v1/agents` | `AgentCreate` (§2.1) | 201 detail | 400 validation, 409 duplicate `agent_id` |
| `PATCH /v1/agents/{agent_id}?tenant_id=…` | `AgentPatch` (§2.2) | 200 detail | 400 validation, 403 seed-protected field, 404 unknown |
| `DELETE /v1/agents/{agent_id}?tenant_id=…` | — | 200 `{agent_id, enabled:false, soft_deleted:true}` | 403 seed (cannot delete a seed), 404 unknown |

Notes:
- Provisioning: `POST` provisions the tenant + seeds idempotently first (same
  `_provision_tenant` path as the reads), so a brand-new tenant can create a
  third agent on its first ever call.
- The tenant param is server-side-injected by the bridge (never client-sent)
  exactly as for the A5 reads (TENANCY.md §1).

### 2.1 `AgentCreate`

```jsonc
{
  "agent_id": "research",          // required, slug (§4)
  "system_prompt": "…",            // required, 1..8000
  "model": "claude-fable-5",       // optional; default = tenant seed model
  "tools": ["get_time"],           // optional; default []
  "memory_policy": "off",          // optional; default "off"
  "budget_monthly_usd": 10.0,      // optional; default DEFAULT_BUDGET_MONTHLY_USD (20),
                                   //   clamped to ≤ tenant cap at validation
  "enabled": true                  // optional; default true
}
```

### 2.2 `AgentPatch` (partial; absent fields unchanged — `exclude_unset`)

```jsonc
{
  "system_prompt": "…?",
  "model": "…?",
  "tools": ["…"]?,
  "memory_policy": "…?",
  "budget_monthly_usd": 12.0?,
  "enabled": false?
}
```

`agent_id` is **not** a PATCH field (immutable; renaming would orphan
sessions/memory/usage keyed on it — DELETE-and-recreate is the explicit path
and is refused for seeds).

**DELETE is a soft-delete** (set `enabled=false`). Sessions, transcripts,
memory, usage, proposals, and events for the agent are **never** hard-deleted
(they remain the tenant's audit/history and the usage meter still counts them,
LIMITS.md §2). A soft-deleted agent disappears from the enabled-agent picker
but its history is still readable; it can be re-enabled via PATCH `enabled:true`.

---

## 3. Seed protection (`personal`, `quill`)

The two seed agents (`app/seeds.py`) are load-bearing (the A5 assistant picker,
the personal auto-recall memory agent, the quill business agent). Protection
rules:

1. **Cannot be deleted / disabled destructively.** `DELETE /v1/agents/personal`
   and `DELETE /v1/agents/quill` → `403 {"detail": "seed agent '<id>' cannot be
   deleted"}`. A PATCH that sets `enabled:false` on a seed → same 403 (a
   disabled seed would break the assistant page).
2. **Cannot be renamed.** `agent_id` is immutable for every agent, so this is
   automatic; a seed cannot be recreated under a different id either (the
   create path rejects the reserved ids `personal`/`quill` — they already
   exist, so a duplicate 409 also covers it).
3. **Can be tuned.** `system_prompt`, `tools`, `model`, `memory_policy`, and
   `budget_monthly_usd` are freely editable on seeds (an operator may add the
   approval-gated write tools to `quill`, tighten a budget, etc.). This matches
   the existing `python -m app.admin set-agent` capability, now exposed in the
   UI.

`is_seed` is computed from `agent_id in {seed.agent_id for SEED_AGENTS}`
(currently `{"personal", "quill"}`) — a single source of truth so adding a
future seed automatically protects it.

---

## 4. Field validation rules (server-side, enforced in `app/agents.py`)

Validation is **server-side and authoritative**; the web form mirrors it for
UX but the API is the belt. A failed rule → `400 {"detail": "<message>"}`.

- **`agent_id` slug:** `^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$` — lowercase
  alphanumeric + internal hyphens, 1..63 chars, no leading/trailing hyphen.
  Must be unique within the tenant (else `409`). Reserved: cannot equal a seed
  id on create (they already exist → 409).
- **`system_prompt`:** non-empty after strip; ≤ `SYSTEM_PROMPT_MAX_CHARS`
  (config, default 8000).
- **`tools`:** every entry must be a key in the registry catalog (§5); unknown
  tool → 400 naming the offender. Deduplicated preserving first-seen order.
  (Note: `memory_save`/`memory_search` may be listed regardless of
  `memory_policy`; the orchestrator strips them at turn time when policy=`off`,
  per the existing A2 rule — listing them is harmless, not an error.)
- **`model`:** must be in the allowed-model set = keys of the pricing table
  (`app/providers/pricing.py` `DEFAULT_PRICING`): `claude-fable-5`,
  `claude-sonnet-4-6`, `claude-haiku-4-5` (source of truth; a versioned
  `@date` suffix is also accepted, mirroring `_lookup`). Unknown alias → 400.
- **`budget_monthly_usd`:** number, `> 0`, and `≤` the tenant's effective
  monthly cap (`budget.resolve_tenant_budget`, LIMITS.md §1: personal tenants
  default $10, org $100, or an explicit override). Over-cap → 400 naming the
  cap. This prevents a single agent's cap exceeding the whole tenant's cap
  (which would make the tenant cap the only real limit).
- **`memory_policy`:** one of `off | tools_only | auto_recall`.
- **`enabled`:** bool.

---

## 5. Tool-palette catalog

The palette is generated from the **registry** (`app/tools/__init__.py`
`REGISTRY`) — the registry is the source of truth; the catalog only adds
human labels, groups, and the approval-gated flag. Exposed to the UI via
`GET /v1/agents/catalog` (agent-cloud) → `GET /v1/agent-cloud/catalog`
(bridge, JWT-gated). Shape:

```jsonc
{
  "groups": [
    {
      "group": "builtin",
      "label": "Built-in",
      "tools": [
        { "name": "get_time", "label": "Current time",
          "description": "Get the current date and time (America/New_York).",
          "approval_gated": false, "memory_tool": false }
      ]
    },
    { "group": "read",   "label": "Quill (read-only)", "tools": [ … 6 tools … ] },
    { "group": "memory", "label": "Memory",            "tools": [ … 2 tools … ] },
    { "group": "write",  "label": "Quill writes (approval-gated)",
      "tools": [ { "name": "quill_project_update", …, "approval_gated": true } … ] }
  ],
  "models": ["claude-fable-5", "claude-sonnet-4-6", "claude-haiku-4-5"],
  "memory_policies": ["off", "tools_only", "auto_recall"]
}
```

Groups (fixed order): `builtin` → `read` → `memory` → `write`.
- **builtin** = `BUILTIN_TOOLS` (`get_time`).
- **read** = `QUILL_TOOLS` (6 read-only Quill tools).
- **memory** = `MEMORY_TOOLS` (`memory_save`, `memory_search`), flagged
  `memory_tool:true` so the UI can note they require a non-`off` memory policy.
- **write** = `QUILL_WRITE_TOOLS` (5), each `approval_gated:true`.

`approval_gated` is true iff the tool name is in `QUILL_WRITE_TOOL_NAMES`.
`descriptions` come verbatim from each `Tool.description`. `label` is a short
human name maintained in `app/agents.py` `TOOL_LABELS` (falls back to the tool
name if unlabeled, so a newly-registered tool never breaks the palette).

**UI guardrail (APPROVALS.md tie-in):** when any `approval_gated` tool is
enabled, the builder shows a persistent notice: *"Write tools never change
Quill directly — every action is queued for human approval in the Quill
queue."* This is copy, not a new mechanism (the double allow-list belt +
proposal-only tools are unchanged).

---

## 6. Templates (clone-to-create)

Templates are **static, server-defined** starter definitions returned by
`GET /v1/agents/templates` (agent-cloud) → `GET /v1/agent-cloud/templates`
(bridge). They are *not* rows — the UI clones a template's fields into the
create form; the user picks a fresh `agent_id`, then `POST /v1/agents`. Shape:

```jsonc
{ "templates": [
  { "template_id": "research-assistant",
    "name": "Research Assistant",
    "summary": "Read-only Quill portfolio Q&A. No writes, no memory.",
    "system_prompt": "…",
    "model": "claude-fable-5",
    "tools": ["get_time", "quill_finance_summary", "quill_pipeline_summary",
              "quill_operations_summary", "quill_customers_summary",
              "quill_intelligence_brief", "quill_list_pending_approvals"],
    "memory_policy": "off",
    "budget_monthly_usd": 10.0 },
  … ] }
```

Three starters (`app/agents.py` `TEMPLATES`):

1. **`research-assistant` — "Research Assistant"** — all 6 read-only Quill
   tools + `get_time`, `memory_policy: off`, no writes. Read-only Q&A.
2. **`ops-analyst` — "Ops Analyst"** — read tools + memory
   (`memory_save`/`memory_search`, `memory_policy: tools_only`) so it can
   remember summaries across sessions. Still no writes.
3. **`project-copilot` — "Project Copilot"** — read tools + memory
   (`auto_recall`) + the approval-gated write tools (`quill_project_update`,
   `quill_project_log_note`, `quill_project_milestone_create`). Clones with
   the write tools pre-checked, so the create form immediately shows the
   approval-queue notice (§5).

`budget_monthly_usd` on every template is clamped to the tenant cap at create
time by the normal §4 validation (a template value never overrides the cap).

---

## 7. Test console

The test console is **not a new endpoint** — it reuses the existing chat SSE
(`POST /v1/agent-cloud/chat`, WEBCHAT.md §3.4, TENANCY.md §1) against the agent
being edited (`agent_id` = the row's id). It lets a user try a saved agent
before/after tuning. Because it hits the *saved* row, the flow is: save (POST/
PATCH) → the agent exists → open the test console → send a message. An unsaved
draft cannot be tested (documented in the UI as "Save to test"). Budgets, rate
limits, tool allow-lists, and approval-gating all apply unchanged (the console
is just the A5 chat client pointed at this agent). Streaming shape, tool chips,
and `budget_exceeded` handling are exactly as `lib/agent-cloud.ts` already
implements.

---

## 8. api bridge (`/v1/agent-cloud/agents`) — JWT-gated, server-side tenant

Mirrors §2 under the bridge prefix, identical to the A5 read bridge
(`api/app/routes/agent_cloud.py`): JWT (`get_current_user`), tenant derived
server-side (`workspace=personal|org`; org → owner/partner only, else 403),
`{detail}` passthrough, `502 {"detail": "agent service unreachable"}` on an
unreachable upstream. `agent_id` is a path/body field (the agent's own id), not
the tenant. Client-sent `tenant_id` is never a schema field anywhere.

| bridge route | upstream |
|---|---|
| `GET  /v1/agent-cloud/agents/{agent_id}` | `GET  /v1/agents/{agent_id}` |
| `POST /v1/agent-cloud/agents` | `POST /v1/agents` |
| `PATCH /v1/agent-cloud/agents/{agent_id}` | `PATCH /v1/agents/{agent_id}` |
| `DELETE /v1/agent-cloud/agents/{agent_id}` | `DELETE /v1/agents/{agent_id}` |
| `GET  /v1/agent-cloud/catalog` | `GET  /v1/agents/catalog` |
| `GET  /v1/agent-cloud/templates` | `GET  /v1/agents/templates` |

`catalog` and `templates` are static and tenant-independent, but the bridge
still requires a valid JWT (no anonymous access) and forwards the derived
tenant for uniformity (upstream ignores it for these two).

---

## 9. Events addendum (EVENTS.md)

One new event type, emitted best-effort (never fails the CRUD call), written
durably to `agentcloud_events` in the same tenant transaction that persists
the row change, then published post-commit:

| type | emitted when | payload |
|---|---|---|
| `agent.updated` | an agent definition is created, patched, or soft-deleted via the CRUD API | `{action: "created"\|"updated"\|"deleted", fields: [str]}` — `fields` lists the changed field names (`["*"]` on create, `["enabled"]` on soft-delete) |

`agent_id` on the envelope is the affected agent; `session_id` is null (not a
session event). This is additive — no existing consumer depends on it.

---

## 10. Web UI route

**Route chosen: `/assistant/builder`.** The top-level `/agents` route is
already taken by the ADK **Agent Registry** (Sprint DC.4, a read-only card grid
of the 9 platform agents) — reusing it would clobber an unrelated feature. The
Agent Builder is the management surface for the *agent-cloud* agents that back
`/assistant`, so it lives directly under that surface at `/assistant/builder`.
The existing `/assistant` chat page is unchanged; it gains a small "Build
agents" link to the builder, and the builder's back arrow returns to
`/assistant`. (The chosen slug is documented here per the brief's "pick,
document" instruction.)

Layout:
- **Agent list** (left/top): the tenant's agents (`useAgentCloudAgents`),
  seeds badged, a **New agent** button (opens the create form with a template
  picker), and each row opens the editor.
- **Editor form:** name/slug (slug disabled when editing), system-prompt
  textarea (char counter vs cap), model picker (from catalog), memory-policy
  selector, budget input (validated ≤ tenant cap, with the cap shown), enabled
  toggle (disabled for seeds with a tooltip), and the **tool palette**.
- **Tool palette:** grouped checkboxes from `GET …/catalog`; the `write` group
  is visually marked and, when any write tool is checked, the approval-queue
  notice (§5) appears.
- **Templates:** the New-agent flow offers the three §6 templates as
  clone-to-create cards.
- **Test console:** a mini chat panel (reusing `sendAgentChat`) targeting the
  saved agent; shown once the agent exists.

`workspace=personal|org` is a page-level selector (owner/partner) mirroring the
assistant page, so org agents can be managed via `workspace=org`.

---

## 11. Safety invariants (carried forward)

1. Tenancy: users only see/edit their own agents; org agents require
   owner/partner + `workspace=org` (TENANCY.md). Client-sent `tenant_id` is
   never a field.
2. Tools remain double-enforced (allow-list at spec-time + `run_tool`
   re-check). The palette is a UI over the same allow-list; it can only ever
   set names that exist in the registry (server rejects the rest).
3. Write tools stay proposal-only + approval-gated (APPROVALS.md). Enabling
   them in the builder changes *what the agent may propose*, never what it may
   execute — execution is still human-approved in the Quill queue.
4. Budgets stay capped at the tenant level (LIMITS.md); the builder cannot set
   an agent budget above the tenant cap.
5. Seeds cannot be deleted/disabled/renamed (§3); history is never
   hard-deleted (§2 soft-delete).
