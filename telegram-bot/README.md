# Quill Telegram Bot

Mobile approval surface for Quill. Wraps the Approval Queue API in a
Telegram bot so Charles can triage Lane 2 / Lane 3 items, see fleet
health, and receive the 7am Daily Brief — all from his phone.

## What it does (Sprint 2.4)

- Pairs a Telegram chat to a Quill user via `/start <code>`
- Lists pending approvals, paginated 5 per page (`/queue`)
- Approve / reject / edit / escalate via short-lived passkey deep-links
- Push notifications on new approvals (silent for Lane 2, loud for Lane 3,
  immediate-high-priority for safety / critical-path / priority=critical flags)
- 7:00 AM ET Daily Brief delivered to Charles + archived to Drive
- Lane 2 (>4h, >8h) and Lane 3 (>12h) reminder cadences
- Sentry instrumentation tagged `service=bot`

## Architecture

```
                 ┌────────────────┐
 Telegram ──────▶│  bot.py        │ ← long-poll
                 │   handlers/    │ ← /start, /queue, /approve, …
                 │   notifier.py  │ ← WS events → push
                 │   scheduler.py │ ← APScheduler: 7am brief, reminders
                 │   api_client   │ ← typed HTTP client
                 │   pairing.py   │ ← HMAC pairing codes
                 │   deeplink.py  │ ← signed 60s URLs to web UI
                 └────────────────┘
                          │
                          ▼
                  Quill Approval Queue API
                          │
                          ▼
                  Web UI (passkey ceremony)
```

## Run it

```bash
cd telegram-bot
pip install -e ".[dev]"
export TELEGRAM_BOT_TOKEN=<from @BotFather>
export TELEGRAM_PAIRING_SECRET=<random-32-bytes>
export QUILL_API_URL=http://localhost:8000
export AGENT_SHARED_SECRET=<same as the API>
quill-bot run
```

For dev iteration without a real bot token, leave `TELEGRAM_BOT_TOKEN`
unset (or export `QUILL_BOT_FAKE_MODE=1`). The bot enters **fake-token
mode**: scheduler still runs and heartbeats to the API, but no Telegram
I/O happens.

## Pairing flow

```
                                    ┌─ admin shell
                                    │  $ quill-bot mint-pair --email charles@…
                                    │  Q1.charles@….1715000000.deadbeef…
                                    │
admin pastes code to Charles  ◀────┘
                                                     ▼
Charles → @QuillOpsBot:  /start Q1.charles@…
                                                     ▼
   bot verifies HMAC + freshness (24h TTL by default)
                                                     ▼
   bot → POST /v1/admin/users/telegram_pair
                                                     ▼
   API sets User.telegram_chat_id = chat_id
                                                     ▼
              "🔗 Telegram paired."
```

The pairing code is HMAC-SHA256-signed (truncated to 16 hex chars) over
`Q1|email|issued_at` using `TELEGRAM_PAIRING_SECRET`. Codes are
single-purpose (the API only updates the User row; redemption itself is
not consumed because the secret-rotation discipline is the real defense).

## Deep links

Telegram cannot run a WebAuthn passkey ceremony, so every consequential
command (approve / reject / edit / escalate) returns a deep link to the
web UI. The link is HMAC-signed with `DEEPLINK_SIGNING_SECRET` and
expires after `DEEPLINK_TTL_SECONDS` (default **60 seconds**, matching
`ACTION_ASSERTION_TTL_SECONDS` on the API so the assertion the user picks
up *also* expires within that window).

URL shape:
```
https://web.example.com/approvals/<id>/<intent>?t=<base64.payload>.<base64.sig>
```

## Daily Brief

```
06:30 ET → fetch inputs (health, pending approvals, critical-path flags)
07:00 ET → render via runtime (`quill-runtime run daily-brief`),
           fall back to deterministic template if runtime unavailable
07:00 ET → send Markdown to Charles's chat + archive to
           /Quill/briefs/YYYY-MM-DD-daily.md (gog CLI, /tmp fallback)
```

If anything fails the bot sends a single
`❌ Daily Brief failed — check Sentry` and stamps the error in the
exception capture path.

## Production deploy

For dev/local, long-polling is fine. For prod, switch to webhooks:

```bash
# Set the webhook URL once
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://bot.quill.example.com/telegram"
```

Then run the bot under a TLS-terminated reverse proxy and wire
`telegram.ext.Application.run_webhook(...)` in place of
`run_polling(...)` (small diff in `bot.py`).

## Environment

| Var | Purpose |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_PAIRING_SECRET` | HMAC key for `/start <code>` |
| `QUILL_API_URL` | Base URL of the Approval Queue API |
| `QUILL_WS_URL` | WebSocket URL (defaults to API URL with ws:// scheme + `/ws/approvals`) |
| `QUILL_WEB_BASE_URL` | Web UI base URL for deep links |
| `AGENT_SHARED_SECRET` | Both `X-Agent-Secret` and `X-Admin` for the bot |
| `DEEPLINK_SIGNING_SECRET` | HMAC key for deep-link tokens (defaults to `ACTION_ASSERTION_SECRET`) |
| `DEEPLINK_TTL_SECONDS` | Deep-link lifetime (default `60`) |
| `DAILY_BRIEF_CHAT_ID` | Charles's chat id for brief + reminders |
| `SENTRY_DSN_BOT` | Sentry DSN for `service=bot` |
| `ENVIRONMENT` | dev / staging / prod (Sentry tag) |
| `QUILL_BOT_FAKE_MODE` | `1` to skip Telegram I/O (dev/tests) |

## Tests

```bash
cd telegram-bot
pytest -q
```

65 tests cover pairing, deep-links, every handler, the WS-event
classifier, the health-poller, all scheduler reminders, the Daily Brief
fallback path, and the CLI.
