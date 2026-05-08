# Quill Platform API

FastAPI service backing the Approval Queue.

## Endpoints

### Approvals (agent-facing — `X-Agent-Secret` header)

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/approvals` | Agent enqueues a proposed action |
| `GET` | `/v1/approvals` | List pending; filters: `lane`, `agent_id`, `workflow`, `status`, `older_than_minutes`, `limit`, `offset` |
| `GET` | `/v1/approvals/{id}` | Full detail incl. all signature records |
| `PATCH` | `/v1/approvals/{id}/cancel` | Agent cancels its own pending item |

### Approvals (human-facing — Bearer JWT)

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/approvals/{id}/decide` | `approve` / `edit_then_approve` / `reject` / `escalate` |
| `GET` | `/v1/approvals/{id}/audit` | Audit trail for this single approval |

### Audit

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/audit/recent` | Last N entries (filter by `event_type`, `actor`) |
| `GET` | `/v1/audit/verify/{approval_id}` | Walk the chain, recompute hashes |
| `GET` | `/v1/audit/verify` | Verify global chain |

### Admin (Charles-only — `X-Admin` header in Sprint 1)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/agents` | Registered agents + trust tiers |
| `PATCH` | `/v1/agents/{agent_id}` | Adjust trust_tier / default_lane / budget / enabled |
| `POST` | `/v1/admin/litigation_hold/{id}` | Suspend an item |
| `GET` | `/v1/admin/health` | Queue depth + audit chain status |
| `POST` | `/v1/admin/audit_verify` | Force a global chain verification |

### Auth (Sprint 1 stubs)

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/auth/register` | Create dev user, returns JWT |
| `POST` | `/v1/auth/login` | Email + password |
| `GET` | `/v1/auth/me` | Current user from JWT |
| `POST` | `/v1/auth/webauthn/*` | Stubs — Sprint 2 |

### Real-time

| Method | Path | Purpose |
| --- | --- | --- |
| `WS` | `/ws/approvals` | WebSocket feed of approval events |
| `GET` | `/sse/approvals` | Server-Sent Events fallback |

## Auth model

- **Agents** (service accounts) authenticate via the `X-Agent-Secret` header, value =
  `AGENT_SHARED_SECRET` env var. Sprint 1 only — Sprint 2 will swap to per-agent JWT
  with rotation.
- **Humans** authenticate via `Authorization: Bearer <jwt>`. Sprint 1 issues JWTs from
  email + password. Sprint 2 will require WebAuthn passkey assertions on every decide.
- **Admin endpoints** gate on the `X-Admin` header (same shared secret) for Sprint 1.

## Audit chain

Every state change appends an `AuditLogEntry` whose `hash = sha256(prev_hash + canonical_payload)`.
The chain is scoped per `approval_item_id`, so any item's history is independently verifiable
without scanning the global log. `GET /v1/audit/verify/{id}` walks and recomputes; tampering
returns `failures: ["hash_mismatch:entry_id=…"]`.

## SLA watcher

A background asyncio task wakes every 60s, finds pending items past `sla_due_at`,
and emits one `approval.sla_breach` audit event per item (idempotent). Sprint 1 logs +
broadcasts to subscribers; Sprint 1.2 will wire Telegram delivery.

## Sprint 1 caveats

- `execute_approval` is a stub: it flips status to `executed` and stamps
  `execution_result=dry_run`. Real Procore / P6 / ACC writes land in Sprint 4.
- WebAuthn endpoints raise `NotImplementedError` — placeholders for Sprint 2.
- Single-process broadcaster — multi-replica needs Redis pub/sub (Sprint 4).
