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

## Audit log resilience (Sprint 2.3)

The audit chain lives in two stores:

1. **Postgres** — the primary, scanned on every approval state change.
2. **Backblaze B2** — an immutable mirror under `b2://$B2_BUCKET/{YYYY}/{MM}/{DD}/{approval_id|global}/{seq}-{hash12}.json`,
   with bucket-level Object Lock (compliance mode, 7-year retention by default).

Every successful `record_event` write enqueues the entry to a background worker
(`AuditMirror`, started in app lifespan) which uploads to B2. When `B2_KEY_ID` /
`B2_APPLICATION_KEY` are absent (dev / CI), the worker falls back to the local
filesystem at `AUDIT_MIRROR_LOCAL_PATH` (default `./_local_audit_mirror/`).

Mirror failures retry with exponential backoff up to `AUDIT_MIRROR_MAX_RETRIES`
(default 5). After exhaustion the entry surfaces in `GET /v1/admin/audit/mirror_status`
as a `failed_entries` row and a Sentry message is emitted.

### Nightly verification

`api/scripts/audit_verify_run.py` runs at 02:00 ET (set `AUDIT_VERIFY_SCHEDULE_CRON`
in the OS crontab; the env var is informational). It:

* Walks every Postgres entry, recomputes its hash, and checks linkage.
* Pulls every mirror object, recomputes, and confirms the `hash` field matches
  Postgres' value byte-for-byte.
* Cross-checks set membership: every Postgres seq in B2 and vice versa.
* Persists a row to `audit_chain_verifications` with `result ∈ {ok, postgres_drift,
  b2_drift, mismatch, missing, error}`.
* On any non-OK result: writes `AUDIT_FREEZE_FLAG_PATH` (default
  `./_audit_freeze.flag`). While that file exists, every `record_event` raises
  `AuditFrozenError` — writes are paused until ops triages and clears the flag
  (`POST /v1/admin/audit/clear_freeze`).

The admin UI surfaces this through `GET /v1/admin/audit/mirror_status`,
`GET /v1/admin/audit/verifications/recent`, `POST /v1/admin/audit/verify_now`,
and `GET /v1/admin/audit/verify_job/{id}`.

### DR replay tool

`api/scripts/audit_mirror_replay.py --since YYYY-MM-DD --until YYYY-MM-DD`
pulls every mirror object in a date range, walks the chain in isolation, and
reports any drift. With `--restore drill.jsonl` it also writes the entries to
a JSONL file you can sideload into a fresh Postgres for restore drills.

### Make targets

```
make audit-verify     # one-shot full-chain verify (with --drain to seed mirror)
make audit-replay     # DR replay; defaults to SINCE=2026-05-01 UNTIL=$(today)
```

### Test path with B2 creds

If you have a B2 application key with write+read on a test bucket:

```
export B2_KEY_ID=...
export B2_APPLICATION_KEY=...
export B2_BUCKET=quill-audit-test
make audit-verify
```

If creds are unset (default in dev/CI), the suite falls back to local-disk mode
automatically and the same code path is exercised, just against the filesystem.

## SLA watcher

A background asyncio task wakes every 60s, finds pending items past `sla_due_at`,
and emits one `approval.sla_breach` audit event per item (idempotent). Sprint 1 logs +
broadcasts to subscribers; Sprint 1.2 will wire Telegram delivery.

## Sprint 1 caveats

- `execute_approval` is a stub: it flips status to `executed` and stamps
  `execution_result=dry_run`. Real Procore / P6 / ACC writes land in Sprint 4.
- WebAuthn endpoints raise `NotImplementedError` — placeholders for Sprint 2.
- Single-process broadcaster — multi-replica needs Redis pub/sub (Sprint 4).
- Audit mirror is single-process; multi-replica deploys need a shared queue
  (Redis or SQS) so every replica's writes are mirrored exactly once.
