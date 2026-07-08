# CHANNELS.md — External channel adapters (Telegram + Google Chat) (Phase D)

This is the canonical contract for Phase D: making a tenant's agents
reachable from **Telegram** and **Google Chat**, with a **pairing flow** that
binds a channel identity (a Telegram chat, a Google Chat space) to a Quill
user's tenant + a chosen agent. As with EVENTS.md / WEBCHAT.md / APPROVALS.md,
do not invent fields outside this document; extend it here first.

**Design anchor:** `QUILL-AGENT-CLOUD-DESIGN.md` §4 "Channels" — one platform
Telegram bot (users pair via a deep-link code) and one published Google Chat
app (space↔tenant binding on first use). Channel adapters feed the **same**
orchestrator turn loop as web chat (`app/orchestrator.py:stream_turn`); they
do **not** fork it.

```
Telegram  ─webhook─┐                                    ┌─ resolve link → (tenant, agent)
                   ├─▶ POST /v1/channels/<p>/webhook ──▶│  stream_turn (collect, non-stream)
Google Chat ───────┘   verify platform secret          └─ send reply via platform API
                                                            (approval → deep link to /queue)
```

## 1. What is (and isn't) in Phase D

- **In:** the `agentcloud_channel_links` table (pairing state), the pairing
  code flow (web generates a code, the bot binds it), inbound webhooks for
  both platforms with signature/secret verification, identity→tenant/agent
  resolution, a single bot reply per inbound message via the same
  orchestrator turn, approval-gated writes surfaced as a web deep link, the
  api bridge pairing/list/revoke endpoints, `channel.linked`/
  `channel.message` events, and a light web Channels page.
- **Out (documented external ops):** BotFather bot creation + `setWebhook`
  (Telegram), and Google Chat app **publication/verification** in the Google
  Workspace Marketplace. The adapter code, webhook handling, and send path
  are complete and testable without these; the one-time Google/Telegram-side
  setup is documented in §11 and KNOWN_ISSUES. Google Chat is marked
  **code-complete, pending Google verification**.

## 2. Pairing flow

Biometrics/passwords for approvals cannot happen inside a bot, and we must
never trust a raw platform id as an identity. So linking is **initiated from
the authenticated web app** and **confirmed from the bot**:

```
1. Authenticated web user (JWT) picks a platform + one of their agents and
   POSTs the api bridge:  POST /v1/agent-cloud/channels/pair
   → api injects tenant server-side, calls agent-cloud
     POST /v1/agents/channels/pair {tenant_id, agent_id, platform}
   → agent-cloud creates a `agentcloud_channel_links` row status='pending'
     with a short, single-use, expiring `pairing_code`.
   → returns {pairing_code, platform, agent_id, expires_at, instructions}.

2. User sends the code to the bot:
   - Telegram:  /start <code>     (or just sends "<code>" as a message)
   - Google Chat:  the user @-mentions/DMs the app with "<code>"

3. The inbound webhook sees an unlinked platform identity carrying a code.
   agent-cloud looks up the pending row by (platform, pairing_code):
   - not found / expired / already used → bot replies "invalid or expired
     pairing code" (never reveals whether a code exists).
   - found & valid → bind: set platform_user_id, platform_chat_id,
     display_name, status='linked', linked_at=now, clear pairing_code.
     Emit channel.linked. Bot replies "✓ Linked to agent <agent_id>."

4. Thereafter, any message from that (platform, platform_chat_id) routes to
   the bound (tenant, agent) and runs a normal orchestrator turn.
```

**Code properties.** `pairing_code` is a URL-safe random token
(`CHANNELS_PAIRING_CODE_BYTES`, default 4 → 6–7 chars base32-ish, short
enough to type). Single-use (cleared on bind). Expires after
`CHANNELS_PAIRING_TTL_SECONDS` (default 900 = 15 min). A tenant may re-pair
the same platform identity to a different agent by generating a new code and
sending it; the bind updates the existing link row for that identity
(one active link per (platform, platform_chat_id)).

## 3. Link table — `agentcloud_channel_links`

Additive, idempotent DDL in `app/migrations.py` (`DDL_D`, one statement
each) + appended to `_RLS_TABLES` (tenant + admin policies, FORCE RLS), same
as every other `agentcloud_*` table.

```
link_id          UUID PK default gen_random_uuid()
tenant_id        TEXT NOT NULL
agent_id         TEXT NOT NULL          -- which agent this channel routes to
platform         TEXT NOT NULL          -- 'telegram' | 'googlechat'
platform_user_id  TEXT                  -- who sent it (set at bind)
platform_chat_id  TEXT                  -- the chat/space (routing key, set at bind)
display_name     TEXT                   -- best-effort human label (set at bind)
status           TEXT NOT NULL DEFAULT 'pending'   -- pending | linked | revoked
pairing_code     TEXT                   -- set while pending, cleared on bind
code_expires_at  TIMESTAMPTZ            -- pending-code expiry
created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
linked_at        TIMESTAMPTZ
revoked_at       TIMESTAMPTZ
```

Indexes:
- `(tenant_id, status)` — list a tenant's links.
- partial UNIQUE `(platform, pairing_code) WHERE status='pending'` — a code
  resolves to at most one pending row (the pairing lookup key).
- partial UNIQUE `(platform, platform_chat_id) WHERE status='linked'` — at
  most one live link per chat/space, so routing is unambiguous.

**Resolution (identity→tenant/agent).** Inbound routing is a lookup on
`(platform, platform_chat_id, status='linked')`. The cross-tenant scan (a
webhook is unauthenticated w.r.t. our tenants — the platform id is all we
have) runs under the **admin RLS policy** (system path, exactly like the
scheduler claim / approvals reconcile); once resolved, the turn and every
per-link write run in a **tenant-scoped** `tenant_session(tenant_id)`.

## 4. Inbound webhook contract

Two endpoints on the orchestrator, both **best-effort** (never 5xx on a
malformed update — that would make the platform retry a poison message):

### 4.1 `POST /v1/channels/telegram/webhook`

- **Auth:** Telegram's `setWebhook secret_token` echoed in the
  `X-Telegram-Bot-Api-Secret-Token` header. Must equal
  `TELEGRAM_WEBHOOK_SECRET`. Mismatch → `403 {"detail": ...}`. Unset secret
  **or** unset `TELEGRAM_BOT_TOKEN` → `503 {"detail": "telegram channel not
  configured"}` + a clear log (degrade cleanly, §9).
- **Body:** a Telegram Bot API [Update]. We handle `message` updates with a
  text body; everything else is acknowledged and ignored (`200 {"ok":
  true, "ignored": ...}`). `message.chat.id` is the routing key
  (`platform_chat_id`); `message.from.id` is `platform_user_id`;
  `message.from.username`/first name → `display_name`.
- **Pairing:** a message whose text is `/start <code>` or exactly a bare
  code (when the chat is not yet linked) is treated as a pairing attempt.
- **Reply:** always `200`; the bot's actual reply is sent via the Telegram
  `sendMessage` API (§5), not in the HTTP response body.

### 4.2 `POST /v1/channels/googlechat/webhook`

- **Auth:** Google Chat signs each request with a Google-issued **Bearer
  JWT** in `Authorization`, audience = the app's project number. Full
  verification requires Google's public certs (a live/ops dependency). We
  verify a shared bearer token (`GOOGLECHAT_VERIFICATION_TOKEN`) as the
  in-code belt and document the production JWT-audience verification as the
  Google-side hardening (§11, KNOWN_ISSUES). Mismatch → `403`. Unset token
  **or** unset `GOOGLECHAT_SERVICE_ACCOUNT_JSON` → `503 {"detail":
  "google chat channel not configured"}`.
- **Body:** a Google Chat [event]: `type` ∈ `ADDED_TO_SPACE`, `MESSAGE`,
  `REMOVED_FROM_SPACE`. We handle `MESSAGE`. `space.name` is the routing key
  (`platform_chat_id`); `user.name` is `platform_user_id`;
  `user.displayName` → `display_name`; `message.text` is the body (leading
  app @-mention stripped).
- **Pairing:** a `MESSAGE` whose text is a bare code (when the space is not
  yet linked) is a pairing attempt.
- **Reply:** Google Chat supports a **synchronous** reply — the JSON
  response body `{"text": "..."}` is posted back into the space. We use the
  sync reply for the bot's message (no async send credential needed for the
  happy path); the async REST `spaces.messages.create` path is implemented
  for out-of-band sends (e.g. approval-resolution wakes) and gated on the
  service-account credential.

## 5. Outbound send (per platform)

`app/channels/<platform>.py` implements `send(chat_id, text)`:

- **Telegram:** `POST https://api.telegram.org/bot<token>/sendMessage`
  `{chat_id, text}`. Uses `TELEGRAM_BOT_TOKEN`.
- **Google Chat:** happy-path replies use the **synchronous webhook
  response** (return `{"text": ...}` from the webhook). The async path
  (`send`) uses `spaces.messages.create` authenticated with
  `GOOGLECHAT_SERVICE_ACCOUNT_JSON` — used only for out-of-band messages
  (approval wakes). Both are behind the config gate.

The HTTP send clients are injectable (a module-level factory) so tests mock
them; **no network in tests**.

## 6. Running the turn — reuse, don't fork

An inbound text message from a linked chat runs exactly one orchestrator
turn via `chat_turn(...)` (the non-streaming collector over `stream_turn`),
`use_stream=False`. The link's `(tenant_id, agent_id)` are passed straight
through, so **everything already built applies unchanged**:

- **Session:** each link carries a `session_id` (created lazily on first
  message, persisted on the link row's routing — see §3 note; Phase D uses a
  per-link session so the conversation has continuity). The turn's
  `session_id` is reused for subsequent messages from that chat.
- **Budget + rate limits (B2):** `ratelimit.enforce(tenant_id, "chat")`
  runs before the turn (a per-tenant abuse limit spanning web + channels);
  the per-agent + per-tenant monthly caps gate inside `stream_turn`. A
  budget refusal is delivered as the bot's reply text (not an error).
- **Tools + approvals (A6):** identical. If the agent calls an
  approval-gated write tool, the proposal lands in the Quill `/queue` as
  usual and the tool returns "pending approval" to the model; the bot's
  reply includes a **deep link** to the web approval queue (§7).
- **Events:** `turn.completed`/`tool.executed`/… emit unchanged; Phase D
  adds `channel.message` (see §8).

## 7. Approval-gated writes in a chat channel

Biometrics/passwords for approvals happen on the web, never in a bot. So
when a channel turn proposes a write:

1. The write tool queues the proposal in the Quill `/queue` (APPROVALS.md)
   and returns "pending approval" to the model — **unchanged**.
2. The orchestrator's reply text (the model's own words) is sent to the
   chat, and the adapter **appends a deep link** to the web approval queue:
   `<CHANNELS_APPROVAL_DEEPLINK_BASE>/queue` (default the Quill app `/queue`
   route). The user taps it, authenticates on the web, and approves there.
3. Resolution wake (A6): the `[system wake]` message lands in the link's
   session as usual. Phase D does **not** proactively push the wake to the
   channel (the wake is passive, same as scheduler reminders / A6 #2); the
   user sees the outcome on the channel's next turn, or in the web queue.
   *(Pushing approval outcomes to the channel out-of-band is a later slice —
   the async `send()` path exists but is not wired to the wake in D.)*

This keeps the security property intact: **a bot can never execute a write;
it can only surface a link to the human-authenticated approval surface.**

## 8. Events addendum (EVENTS.md)

Two new types appended to `EVENT_TYPES`:

| type | emitted when | payload |
|---|---|---|
| `channel.linked` | a pairing code is redeemed and a link goes `linked` | `{link_id, platform, platform_chat_id, display_name}` |
| `channel.message` | an inbound channel message runs a turn | `{link_id, platform, direction: "inbound", chars}` — `agent_id`/`session_id` set from the link; no message content in the event (privacy) |

Both are written durably to `agentcloud_events` (RLS'd, tenant-scoped) and
published best-effort like every other event; neither can fail a turn.

## 9. Config (all `app/config.py`, degrade cleanly)

| Setting | Default | Meaning |
|---|---|---|
| `CHANNELS_ENABLED` | `false` | Master flag. When false, every webhook returns `503` and pairing endpoints return `503` — the whole feature is dark. |
| `TELEGRAM_BOT_TOKEN` | `""` | Platform bot token (BotFather). Unset ⇒ Telegram webhook `503`. |
| `TELEGRAM_WEBHOOK_SECRET` | `""` | `setWebhook secret_token`; verified per request. Unset ⇒ Telegram webhook `503`. |
| `GOOGLECHAT_VERIFICATION_TOKEN` | `""` | In-code bearer belt for the Chat webhook. Unset ⇒ Google Chat webhook `503`. |
| `GOOGLECHAT_SERVICE_ACCOUNT_JSON` | `""` | SA creds JSON for the async REST send path. Unset ⇒ async send disabled (sync reply still works). |
| `GOOGLECHAT_PROJECT_NUMBER` | `""` | App's GCP project number = the JWT audience for production verification (§11). |
| `CHANNELS_PAIRING_TTL_SECONDS` | `900` | Pairing-code lifetime. |
| `CHANNELS_PAIRING_CODE_BYTES` | `4` | Entropy of the code (token bytes). |
| `CHANNELS_APPROVAL_DEEPLINK_BASE` | `https://app.quill…` | Base URL for the web approval-queue deep link appended to bot replies. |
| `CHANNELS_SEND_TIMEOUT_SECONDS` | `15` | Outbound send HTTP timeout. |

Secrets are env/Secret-Manager style (never hardcoded), same pattern as
`TELEGRAM_BOT_TOKEN` etc. in the notification bot. Per-tenant **own-bot
tokens** (design §4 "power users may plug in their own bot token") reuse the
B2 per-tenant secrets store (`SECRETS.md`) — deferred past D; the platform
bot is the D scope.

## 10. Security

1. **Webhook verification per platform** (Telegram secret-token header;
   Google Chat bearer token in-code + documented JWT-audience production
   verification). No verification ⇒ `403`.
2. **Never trust a raw platform id as identity.** A platform identity gains
   a tenant only by redeeming a code minted by an authenticated web user.
3. **Pairing codes:** single-use, short-TTL, high-entropy, and the pairing
   lookup **never reveals** whether a code exists (uniform "invalid or
   expired" reply) — no code-enumeration oracle.
4. **Cross-tenant resolution runs under the admin RLS policy** (system
   path); all per-link work runs tenant-scoped. RLS on
   `agentcloud_channel_links` is proven by the pg isolation sweep.
5. **No writes from a bot.** Approval-gated writes surface a web deep link;
   execution requires web authentication (§7).
6. **Best-effort webhooks:** a malformed update is acknowledged `200` and
   ignored — never a 5xx (which would make the platform retry a poison
   message) and never a crash.
7. **Rate limits + budgets** (B2) apply to channel turns exactly as to web
   chat — the same per-tenant abuse ceiling.

## 11. One-time external setup (out of code scope; documented)

**Telegram (platform bot).** App code cannot create a Telegram bot or its
token — that is a BotFather (human) step:
1. In BotFather: `/newbot` → get `TELEGRAM_BOT_TOKEN`.
2. Choose a `TELEGRAM_WEBHOOK_SECRET` (any strong random string).
3. Register the webhook (one HTTPS call, ops-side):
   `curl "https://api.telegram.org/bot<token>/setWebhook" -d
   url=<service-url>/v1/channels/telegram/webhook -d
   secret_token=<TELEGRAM_WEBHOOK_SECRET>`.
4. Deploy with `CHANNELS_ENABLED=true`, `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_WEBHOOK_SECRET` set (Secret Manager).
The adapter, webhook handler, pairing, and `sendMessage` are all
implemented and unit-tested with a mocked HTTP client; only BotFather +
`setWebhook` are external.

**Google Chat (published app).** Genuinely multi-tenant by design, but
**publishing a Chat app requires Google Workspace Marketplace
verification/listing — a human/ops step outside code**:
1. Enable the **Google Chat API** in the GCP project.
2. Create a service account; grant it the Chat bot role; download JSON →
   `GOOGLECHAT_SERVICE_ACCOUNT_JSON` (for the async send path).
3. Configure the Chat app (App name, avatar, **HTTP endpoint** =
   `<service-url>/v1/channels/googlechat/webhook`, a **verification token**
   → `GOOGLECHAT_VERIFICATION_TOKEN`, and the project number →
   `GOOGLECHAT_PROJECT_NUMBER`).
4. **Marketplace listing + Google verification** (OAuth/app review) to make
   the app installable outside the developer's own Workspace.
5. Production hardening: verify the inbound **Bearer JWT** signature against
   Google's public certs with audience = `GOOGLECHAT_PROJECT_NUMBER`
   (the in-code token check is the interim belt).
The adapter + webhook + sync reply + async send are implemented and
unit-tested with mocks. **Status: code-complete, pending Google
verification** (KNOWN_ISSUES / D).

## 12. api bridge surface (Quill API, `get_current_user`-gated)

Server-side tenancy from B1 (WEBCHAT.md §1 / TENANCY.md): the client never
supplies `tenant_id`; the bridge injects `user-{id}` (personal) or the org
tenant (`workspace=org`, owner/partner only). All under `/v1/agent-cloud/
channels/*`, `{detail}` envelope, 502 on agent-cloud unreachable.

- `POST /v1/agent-cloud/channels/pair` `{platform, agent_id,
  workspace?}` → `{link_id, platform, agent_id, pairing_code, expires_at,
  instructions}`. Proxies agent-cloud `POST /v1/agents/channels/pair`.
- `GET /v1/agent-cloud/channels?workspace=…` → `{items:[{link_id, platform,
  agent_id, status, platform_chat_id, display_name, created_at,
  linked_at}], total, limit, offset}`. Pending links show a masked code
  hint but never the raw code after creation.
- `POST /v1/agent-cloud/channels/{link_id}/revoke` → `{link_id, status:
  "revoked"}`. 404 unknown/cross-tenant (indistinguishable).

agent-cloud endpoints backing these (tenant_id as body/query param, exactly
like agents/schedules): `POST /v1/agents/channels/pair`,
`GET /v1/agents/channels`, `POST /v1/agents/channels/{link_id}/revoke`.
Route order: the literal `/v1/agents/channels*` routes are declared **before**
the `/v1/agents/{agent_id}` path-param routes so `channels` is never shadowed
(same discipline as catalog/templates in Phase C).

## 13. Web (light)

`/assistant/channels`: pick a platform + one of the tenant's agents →
generate a pairing code (shown with copy-paste instructions per platform) →
list existing links (platform, agent, status badge) → revoke. Keeps the
heavy lift in the backend; this is a thin form over the bridge endpoints.
