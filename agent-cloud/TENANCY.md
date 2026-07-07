# TENANCY.md — per-user tenancy + isolation attack suite (Sprint B1)

Phase B, first slice (design doc §7 "Signup provisioning hook in Quill,
RLS + isolation test suite"). This document is the canonical contract for
how Quill users map onto agent-cloud tenants, how tenants get provisioned,
and what the isolation attack suite proves. It **amends WEBCHAT.md §1**
(the Phase A "one deployment = one tenant" rule); everything else in
WEBCHAT.md (shapes, SSE, error envelope) is unchanged.

## 1. Tenant mapping rule (B1)

```
tenant_id = "user-{user.id}"        # personal workspace — the default
tenant_id = AGENTCLOUD_TENANT_ID    # shared org workspace ("quill-main")
                                    # — owner/partner only, opt-in
```

- `user.id` is the Quill `users.id` (uuid string), taken from the verified
  JWT (`get_current_user`) — **never from the client**. `tenant_id` remains
  a non-field on every bridge schema; any client-sent `tenant_id` (body or
  query) is ignored exactly as in A5.
- Every bridge route accepts an optional `workspace` selector —
  `"personal"` (default) | `"org"`:
  - `personal` → `user-{user.id}` for any authenticated user.
  - `org` → `AGENTCLOUD_TENANT_ID` (default `quill-main`), permitted only
    for `owner` and `partner` roles; any other role gets
    `403 {"detail": "org workspace requires owner or partner role"}`.
    `workspace` is an enum, not a tenant id — the client still cannot name
    an arbitrary tenant. Invalid values are a 422 (enum validation).

Why this shape (design decision, kept deliberately small):

- Per-user personal workspaces are the Phase B semantic (design §3.2
  "tenant = Quill account"; each user is an account).
- The `org` selector exists **only** to keep the Phase A shared workspace
  (`quill-main`) reachable — all pre-B1 sessions/memories/schedules live
  there and must not be orphaned. Restricting it to owner/partner matches
  who actually used the A5 assistant (observers never had meaningful
  workspace data of their own and get a clean personal workspace).
- No new tables, no tenant column in Quill, no membership model. A real
  multi-org membership model is out of scope until the design doc calls
  for it; this rule is fully derivable from `users.role` + `users.id`.

`AGENTCLOUD_TENANT_ID` keeps its A5 meaning: the deployment's shared/org
tenant constant. Smoke deployments keep the `smoke-` cheap-model seeding
convention for the org tenant; personal tenants (`user-…`) seed on
`MODEL_DEFAULT` like any other tenant.

## 2. Provisioning flow (signup hook)

Tenant provisioning in agent-cloud is already idempotent
(`INSERT … ON CONFLICT DO NOTHING` via `directory.list_agents` /
`_prepare`): the first `GET /v1/agents?tenant_id=…` creates the tenant row
and seeds the `personal` + `quill` agents. B1 reuses exactly that path —
no new agent-cloud endpoint.

The Quill api calls `agent_cloud.provision_user_tenant(user_id)` at every
point where a **new user row is created**:

| Auth path | When the hook fires |
|---|---|
| `POST /v1/auth/register` (dev fallback) | after the user row commits |
| `POST /v1/auth/google` | only on the first-touch branch that creates the user |
| `POST /v1/auth/login` (dev fallback) | never creates users → no hook. Login/passkey paths rely on the lazy fallback below. |

Properties:

- **Best-effort / non-blocking:** the hook is `await`ed with a hard
  `asyncio.wait_for` timeout (`AGENTCLOUD_PROVISION_TIMEOUT_SECONDS`,
  default 3s) and swallows *every* exception (logged). Registration can
  never fail — and is delayed at most ~3s — because agent-cloud is down.
- **Idempotent:** re-firing (re-login, retried signup) is a no-op upstream.
- **Lazy fallback (the real safety net):** provisioning also happens
  implicitly on the user's first `GET /v1/agent-cloud/agents` (the web
  assistant page always lists agents first), because that proxies
  agent-cloud's provisioning read. A user whose signup-time hook was lost
  still gets a working workspace on first visit. The hook exists to make
  the first visit instant, not to be load-bearing.

## 3. Backfill / compatibility (existing quill-main data)

**No data migration.** Everything created before B1 lives under tenant
`quill-main` and stays there, fully readable/writable via
`workspace=org` for owner/partner users:

- `white.1284@gmail.com` (owner) — sees quill-main via `workspace=org`;
  gets a fresh personal workspace (`user-{id}`) as the new default.
- `sidaoui.khawla@gmail.com` (partner) — same: org access + fresh personal
  default.
- `charlesmitchell.r` / any observer-role user — personal workspace only.
  Any pre-B1 content they contributed to the shared workspace remains in
  quill-main (visible to owner/partner, not to them). Accepted for B1 and
  tagged in KNOWN_ISSUES (observers were read-only spectators of the
  shared workspace by role semantics anyway).

Because the web frontend defaults to `workspace=personal`, existing users
will see an **empty session list** on their first post-B1 visit — the old
shared history is one `workspace=org` toggle away (owner/partner). Tagged
visible-tolerable in KNOWN_ISSUES.

Rollback story: setting the frontend/bridge to `workspace=org`-always is
equivalent to the A5 behavior; no destructive change is made anywhere.

## 4. Isolation threat model

Assets: per-tenant sessions/transcripts, memories, proposals, schedules,
jobs, events, usage. Adversary: an authenticated Quill user (valid JWT)
attempting to read or write another tenant's data; or an unauthenticated
network caller hitting internal endpoints.

Trust boundaries and their belts:

1. **Browser → api bridge:** JWT (`get_current_user`); tenant derived
   server-side from `user.id` + `role` (this doc §1). Client-supplied
   `tenant_id` is not a schema field anywhere.
2. **api → agent-cloud:** network/IAM-gated (A1); `tenant_id` in
   query/body is set only by the bridge.
3. **agent-cloud app layer:** every query filters `tenant_id`.
4. **Postgres RLS:** ENABLE+FORCE on all `agentcloud_*` tables; tenant
   policy on `current_setting('app.tenant_id', true)` set per-transaction;
   admin policy only for the maintenance CLI / cross-tenant system paths
   (scheduler claim).
5. **Internal endpoints** (`/v1/internal/*`): shared-secret header,
   disabled while the secret is unset.

404-not-403 rule: cross-tenant probes on resource ids must be
indistinguishable from nonexistent ids (no existence oracle).

## 5. Attack-test catalog (B1 suite)

api side — `api/tests/test_agentcloud_tenancy.py`:

- A1. Every bridge route derives `tenant_id = user-{id}` per user (two
  distinct users → two distinct tenants forwarded upstream).
- A2. Client-supplied `tenant_id` (chat body AND query params on every GET
  route) never reaches agent-cloud.
- A3. `workspace=org` → `quill-main` for owner and partner; 403 for
  observer; invalid workspace value → 422.
- A4. SSE chat stream forwards the per-user tenant (a user cannot stream
  into another tenant, including via a stolen `session_id` — upstream 404
  becomes an SSE `error` event; covered end-to-end agent-cloud side, B7).
- A5. Provisioning hook fires on register + google first-touch, does NOT
  fire on plain login / existing-user google sign-in, and registration
  succeeds (2xx) when agent-cloud is unreachable.

agent-cloud side — `tests/test_isolation.py` (sqlite, app layer) +
`tests/test_isolation_pg.py` (pg-gated, RLS layer):

- B1. Transcript read with tenant B's GUC-scoped request on tenant A's
  session id → 404 (`GET /v1/agents/sessions/{id}`).
- B2. Chat turn (non-stream) with tenant A's `session_id` under tenant B →
  404, and no message is appended to A's session.
- B3. SSE chat attach to another tenant's session → `error` event with
  `status: 404`, stream ends, no leakage.
- B4. Sub-agent job read cross-tenant → 404; job creation with a foreign
  `session_id` (parent wake target) → 404.
- B5. Schedules: GET/PATCH/DELETE another tenant's schedule id → 404;
  creation with a foreign target `session_id` → 404.
- B6. Approvals notify: wrong/missing `X-Agent-Secret` → 403; correct
  secret but another tenant's `quill_approval_id` under the wrong
  `tenant_id` → finalizes nothing (`finalized: false`), the victim's
  proposal stays pending.
- B7. Scheduler tick: due schedules of tenants A and B fire into their own
  tenants only (job rows + sessions land in the owning tenant's
  namespace).
- B8. Session list / agents list never contain another tenant's rows.
- B9 (pg). **Systematic RLS sweep over every table in
  `migrations._RLS_TABLES`** (tenants, agents, sessions, messages, usage,
  memory, events, jobs, schedules, proposals — the list is imported, so a
  future table added to RLS is automatically covered): with tenant B's
  GUC → zero tenant-A rows; with no GUC → zero rows; forged INSERT with
  mismatched GUC → rejected by policy `WITH CHECK`.
- B10 (pg). Seed-row completeness guard: the sweep fails if any
  `_RLS_TABLES` entry has no seeded fixture row (prevents a silently
  green-but-empty test).
- B11. Quill read tools (X-Agent-Secret path, api side, existing A5/A6
  suites) remain tenant-scoped: covered by asserting the bridge is the
  only caller that sets tenant and by the existing `test_agent_cloud.py`
  derivation tests updated for per-user tenancy.

## 6. Config

| Setting | Where | Default | Meaning |
|---|---|---|---|
| `AGENTCLOUD_TENANT_ID` | Quill api | `quill-main` | The shared **org** tenant (was: the only tenant). |
| `AGENTCLOUD_PROVISION_TIMEOUT_SECONDS` | Quill api | `3.0` | Hard cap on the best-effort signup provisioning call. |

## 7. Out of scope (B2+)

Per-tenant budgets/meters beyond the existing per-agent monthly cap,
per-tenant secrets (KMS), rate limits, org membership model, moving/
merging quill-main history into personal workspaces.
