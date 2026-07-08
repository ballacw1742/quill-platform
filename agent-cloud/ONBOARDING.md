# Quill Agent Cloud — Onboarding & Operator Guide

Welcome to Quill Agent Cloud — your agents, in the cloud, with the same
approval-gated safety you already trust in Quill. This guide has two halves:
a **getting-started flow** for anyone new to the platform, and an
**operator/cutover summary** for whoever runs the go-live.

> Source of truth for this guide lives in `agent-cloud/ONBOARDING.md`; the
> in-app first-run experience mirrors the "Getting started" section, and the
> go-live mechanics live in `agent-cloud/CUTOVER.md`.

---

## Part 1 — Getting started (for every new tenant)

### What is an agent?

An **agent** is a saved, reusable assistant: a system prompt + a model + a
curated set of tools + a monthly budget. Agents are *data* — you create and
tune them in the Agent Builder, and each one keeps its own memory, sessions,
and usage history. You start with two seeded agents:

- **Personal** — your general-purpose assistant. Memory is on
  (`auto_recall`), so it remembers what matters across conversations.
- **Quill** — a portfolio assistant with read-only access to Quill data
  (finance, pipeline, operations, customers, approvals). Memory is off.

Everything runs inside **your own tenant** (an isolated workspace derived
from your Quill login). You never see another tenant's data, and they never
see yours — enforced at the app layer *and* by Postgres row-level security.

### The 3 starter templates

When you build a new agent, you can start from a template instead of a blank
prompt (Agent Builder → *New from template*):

1. **Research Assistant** — gathers, summarizes, and organizes information.
   Memory on.
2. **Ops Analyst** — analytical, structured, good for status/risk/metrics
   work over your data.
3. **Project Copilot** — a hands-on project helper; pairs well with
   approval-gated write tools when you're ready.

Pick one, tweak the prompt/model/budget, save, and test it in the built-in
console.

### How to pair a channel

Want to talk to an agent from **Telegram** or **Google Chat**? Pair it:

1. Go to **Assistant → Channels** (the link icon).
2. Pick a platform + one of your agents → **Generate pairing code**.
3. Send that code to the bot. It binds the chat to your agent (single-use,
   expiring code — no code, no access).
4. Manage or revoke links from the same page.

*(Channels are dark until the operator enables them and registers the bots —
see Part 2. Until then the pairing page will tell you it's unavailable.)*

### How approvals work

Agents **never** write to a system of record on their own. When an agent
wants to make a change (create a project entry, post an estimate, etc.), it
**queues an approval item** in the Quill approval queue instead of executing.
A human reviews and approves or declines. Only then does the write happen —
and every step is written to the audit log.

- **Lane 1 (auto):** pre-approved low-risk classes still record an audit
  entry.
- **Lane 2 (single-sig) / Lane 3 (dual-sig):** require one or two human
  approvals.

When your approval resolves, you'll see it on your next turn in that session
(a system "wake" message). This means prompt injection can't *do* anything
unapproved — the worst case is a queued item a human declines.

### Budgets & limits

Every workspace has a **monthly budget** (default $10 for a personal
workspace) and each agent has its own cap. When a cap is reached, turns are
**politely refused with no model call** — never an error, never a surprise
bill. Watch your spend anytime at **Assistant → Usage & budget**:
month-to-date spend, remaining budget, per-agent meters, and token counts.
Per-minute **rate limits** protect against runaway loops.

### Your first five minutes

1. Open **Assistant** and say hello to the **Personal** agent.
2. Ask it to remember something ("remember that I prefer concise answers"),
   then start a new chat and confirm it recalls it.
3. Open **Agent Builder**, create an agent from the **Research Assistant**
   template, and test it in the console.
4. Open **Usage & budget** to see your meters.
5. (Optional) Pair a channel once the operator has enabled them.

---

## Part 2 — Operator / cutover summary

This is the short version; the full runbook with exact `gcloud`/console
commands, the per-service env/secret matrix, and reversibility notes is
`agent-cloud/CUTOVER.md`. Feature parity vs. the old OpenClaw workflow and
the staged rollout plan are in `agent-cloud/MIGRATION.md`.

### What's live on defaults vs. staged

The platform serves **web chat, the Agent Builder, budgets/meters, and
approvals** today on all-default backends. The following upgrade a subsystem
from its safe default to its production backend — each is a one-time external
op + a config flip, and each is reversible:

| Subsystem | Default | Prod | External op needed |
|---|---|---|---|
| Embeddings / pgvector | keyword fallback | Gemini + `vector` | `CREATE EXTENSION vector` (privileged role) |
| Event bus | `inline` | `pubsub` | create topics + dead-letter sub |
| Sub-agent jobs | `local` | `cloudrun` | create Cloud Run Job + IAM |
| Scheduler | `loop` | `cloudscheduler` | create Cloud Scheduler job + secret |
| Tenant secrets | `plaintext-dev` ⚠️ | `kms` | create KMS keyring/key + IAM |
| Telegram | off | on | BotFather token + `setWebhook` |
| Google Chat | off | on | Marketplace/Chat API verification |
| Channels master | `CHANNELS_ENABLED=false` | `true` | flip after per-platform setup |

⚠️ **Never leave `SECRETS_BACKEND=plaintext-dev` in a promoted environment** —
it stores tenant secret values unencrypted by design (the name is a warning).

### Go-live sequence (operator owns the final switch)

1. Do the external ops above for the subsystems you want in prod
   (CUTOVER.md §1–§9).
2. Run the **dogfood seed** to make Charles tenant #1 with a real working
   agent (`scripts/dogfood_seed.py`; supports `--dry-run`).
3. Live-test the canonical paths: web chat, a scheduled reminder, a
   sub-agent job, an approval-gated write, a paired channel message.
4. Soak in parallel with OpenClaw (dogfood → limited → full — MIGRATION.md).
5. **Only then** decide to retire OpenClaw. Nothing in the codebase flips
   that switch — it's a deliberate human decision.

### Health check gotcha

External health checks must hit **`GET /health`**, not `/healthz` (Google's
frontend intercepts `/healthz` on `*.run.app`). See CUTOVER.md §11.

---

*Generated as part of Phase E (cutover staging). Everything described here is
ready-to-activate; nothing is flipped live automatically.*
