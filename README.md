# Quill Platform

Operational tooling for a $10B / 1.7 GW hyperscale data center construction program.
Sprint 1.1 ships the **Approval Queue** — the backbone every Agentic PMO agent depends on.

## What this is

Every consequential write (an RFI classification, a submittal review, a P6 schedule
update, a procurement alert) flows from an agent → into this queue → out only after
the right humans have signed. The queue tracks lanes, SLAs, citations, audit chain
integrity, and execution outcomes.

```
agent (rfi-triage, submittal-spec-validator, …)
   │
   ▼
POST /v1/approvals  ── ApprovalItem (pending)
                          │
                          ▼
                 lane-routing + SLA timer
                          │
                  ┌───────┴────────┐
                  │ Lane 1: auto   │ Lane 2: Charles signs
                  │ Lane 3: Charles + partner
                  ▼
              POST /v1/approvals/{id}/decide
                          │
                          ▼
                   execute + audit-chain commit
```

## Repo layout

```
quill-platform/
├── api/                  ← FastAPI Approval Queue API
│   ├── app/              ← models, routes, services
│   ├── alembic/          ← schema migrations
│   ├── scripts/          ← seed + smoke
│   └── tests/            ← pytest suite
├── docker-compose.yml    ← Postgres 16 + pgvector + API
├── Makefile              ← install / dev / test / migrate / seed / smoke
├── pyproject.toml
└── .env.example
```

## Quick start

```bash
cp .env.example .env
make install
docker-compose up -d        # Postgres 16 + pgvector
make migrate                # apply schema
make seed                   # Charles user + agent fleet + 3 sample approvals
make dev                    # API on http://localhost:8000
```

Then in another shell:

```bash
make smoke                              # POST a sample approval
curl http://localhost:8000/v1/admin/health
open http://localhost:8000/docs         # Swagger UI
```

If you don't have Docker handy, the API also runs against SQLite for local
iteration — set `DATABASE_URL=sqlite+aiosqlite:///./quill_dev.db` in `.env`.

## Testing

```bash
make test
```

Covers schema validation, full lifecycle (create → list → decide → execute),
audit-chain tamper detection, Lane 3 dual approval, and SLA breach firing.

## Environment

See `.env.example`. The big knobs:

| Var | Purpose |
| --- | --- |
| `DATABASE_URL` / `DATABASE_URL_SYNC` | Async + sync SQLAlchemy URLs |
| `SECRET_KEY` | JWT signing (Sprint 1 dev sessions) |
| `AGENT_SHARED_SECRET` | Service-account header for agent → API calls (Sprint 1) |
| `SENTRY_DSN` | Optional error reporting |
| `CORS_ORIGINS` | Comma-separated allow-list |
| `TELEGRAM_NOTIFY_CHAT_ID` | SLA-breach notification target (stub) |

## Architecture

- FastAPI + SQLAlchemy 2.0 async
- Postgres 16 (+ pgvector for future semantic context lookups)
- Append-only audit log, sha256-chained per approval
- WebSocket `/ws/approvals` (+ SSE `/sse/approvals`) for the UI feed
- Background SLA watcher tags breaches once and fires events for downstream notifiers
- Sprint 1 auth: dev passwords + service-account secret. Sprint 2: WebAuthn passkeys.

## Roadmap

- **Sprint 1.1** — Approval Queue API end-to-end, audit chain, lanes, SLA, seed
- **Sprint 1.2** — Approval UI (Next.js) + Telegram notifier
- **Sprint 2.1** — Quill Agent Runtime (LLM-driven classifiers/drafters)
- **Sprint 2.2** — WebAuthn passkeys, partner role provisioning
- **Sprint 2.3 (this)** — Audit log offsite mirror (Backblaze B2) + nightly chain verification + DR replay
- **Sprint 3** — Trust-tier autopilot, monthly token budgeting, escalation routing
- **Sprint 4** — Real Procore / P6 / ACC executors replace the Sprint 1 stub

## Audit log resilience

The audit chain is the most important data asset in Quill — it's what protects
Charles in disputes with the hyperscaler three years from now. Sprint 2.3 makes
it tamper-evident across two storage tiers:

* **Postgres** is the primary, scanned on every approval state change.
* **Backblaze B2** is an immutable offsite mirror with Object Lock (compliance,
  7-year retention). Every successful `record_event` write enqueues to a
  background worker that uploads within ~seconds.
* A nightly job (`make audit-verify`) walks both stores, recomputes every hash,
  cross-checks set membership, and persists a result row. On any drift /
  mismatch / missing entry, audit writes are paused via a freeze flag and
  Charles is paged via Sentry + Telegram.
* `make audit-replay` is a disaster-recovery tool that pulls a date range from
  B2 and verifies the chain in isolation; with `--restore` it can sideload to
  a fresh Postgres for restore drills.

In dev or when B2 creds are unset, the mirror falls back to a local directory
(`./_local_audit_mirror/`) so the same code path is exercised end-to-end.

## License

Proprietary — internal use only.
