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

## Running with mock data (Sprint 3)

Mock-data feeders simulate **QPB1** — a fictional $10B / 1.7 GW / 4-building
hyperscale data center build, ground-up start 2026-06-23. Once running, the
Approval Queue grows realistically (RFIs, submittals, DFRs, vendor updates,
hyperscaler inbound), the audit chain extends, and the Daily Brief has
something to say.

```bash
make docker-up                 # Postgres only (or use SQLite via .env)
make migrate seed              # baseline
make dev &                     # API on http://localhost:8000

make mock-bootstrap            # write QPB1 spec corpus, subs, POs, IMS
make mock-start                # background daemon — fast mode (events every 15-120s)
sleep 300                      # ~5 minutes is enough to populate the queue

make mock-status               # show pid + dispatch log line count
curl -s -H "X-Admin: dev-agent-secret-change-me" \
     http://localhost:8000/v1/admin/health | jq

make daily-brief-now           # render the Daily Brief from real synthetic data

make mock-stop                 # graceful shutdown
```

Finer-grained control is via the `quill-mock` CLI — see
[`mock-data/README.md`](mock-data/README.md) for the full surface
(`bootstrap`, `start --fast/--realistic`, `tick --feeder …`, `status`).

For stress testing without APScheduler:

```bash
.venv/bin/python runtime/scripts/replay_week.py --days 7 --minutes 5
```

## Telegram bot (Sprint 2.4)

Mobile approval surface + 7am Daily Brief delivery. See
`telegram-bot/README.md` for the full doc.

Quick path:

```bash
make bot-install                                    # one-time
export TELEGRAM_BOT_TOKEN=<from @BotFather>
export TELEGRAM_PAIRING_SECRET=$(openssl rand -hex 32)

# Mint a pairing code, then redeem from Telegram with /start <code>:
make bot-mint-pair EMAIL=charles@example.com

# Run the bot (long-polling). Without TELEGRAM_BOT_TOKEN the bot enters
# fake-token mode — scheduler still runs and heartbeats to
# /v1/admin/scheduler/jobs so the API can show what's queued.
make bot-dev
```

Commands available in Telegram: `/start <code>`, `/queue`, `/approve <id>`,
`/reject <id> <reason>`, `/edit <id>`, `/escalate <id>`, `/health`,
`/brief`, `/help`.

Decisions that need a passkey assertion (approve / reject / edit /
escalate) deliver a **60-second** signed deep link to the web UI;
Telegram cannot run a WebAuthn ceremony itself.

### Passkey re-registration after the quillpm.com move

The app now lives at **quillpm.com**, so the WebAuthn Relying Party ID is
`RP_ID=quillpm.com`. Any passkey registered before the move (under the old
`*.run.app` RP) is **orphaned** — browsers refuse to use it on the new
domain — and must be re-added at **/profile/passkeys**.

Until a user re-registers (and for anyone who never had a passkey, e.g.
Google-SSO-only accounts), approvals fall back to **password re-auth**:
`POST /v1/auth/password/challenge` mints the *same* intent-bound, one-shot,
60-second action-assertion the passkey path produces (with a
`method="password"` claim), so `/v1/approvals/{id}/decide` accepts it
unchanged. Two proofs are still required — a live bearer session **and** the
account password — and the endpoint is `AUTH_LIMIT` rate-limited (10/min per
IP), identical to `/v1/auth/login`. Decision records store
`auth_method="password"` so a password-confirmed approval stays
distinguishable from a passkey-signed one in the audit trail. The web approve
flow offers this automatically when the passkey ceremony fails or no usable
passkey exists, plus a manual “Use password instead” escape hatch.

Daily Brief lands at **07:00 ET** every morning, archived to Drive at
`/Quill/briefs/YYYY-MM-DD-daily.md`. If the runtime is unreachable, the
bot falls back to a deterministic Markdown brief so you still get the
7am push.

## Sentry (multi-service)

- API:     `SENTRY_DSN_API`    (or legacy `SENTRY_DSN`)
- Runtime: `SENTRY_DSN_RUNTIME`
- Bot:     `SENTRY_DSN_BOT`

Every captured event is tagged with `service`, `environment`, `release`,
and (where applicable) `request_id`, `approval_id`, `agent_id`, `run_id`,
`chat_id`. PII (payloads, prompts, completions, tokens, secrets) is
scrubbed by per-service `before_send` hooks before transmission. Tests
verify that init is idempotent and a no-op when no DSN is set.

## License

Proprietary — internal use only.
