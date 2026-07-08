# MIGRATION.md — OpenClaw → Quill Agent Cloud (Phase E)

What moving from the current **OpenClaw-based workflow** (Axe running on
Charles's Mac Studio as his "brain") to **Quill Agent Cloud** actually looks
like: an honest feature-parity map, what's equivalent vs. a real gap, and the
**staged rollout** (dogfood → limited → full).

> This document is descriptive, not a switch. Nothing here retires OpenClaw.
> The go-live mechanics are in `CUTOVER.md`; the retire decision is Charles's
> (CUTOVER.md §13).

---

## 1. The shape of the move

OpenClaw today is a **single-tenant, machine-level agent**: it has shell/exec
on the Mac, a local workspace, cron heartbeats, a memory folder, and can
spawn sub-agents. Quill Agent Cloud is a **multi-tenant, sandboxed product**:
agents are data, tools are curated and allow-listed, all writes to systems of
record are approval-gated, and there is no machine-level blast radius.

The migration is therefore **not a lift-and-shift** — it's a re-homing of the
*safe* capabilities onto a hardened platform, deliberately dropping the
machine-level surface (that's the point, per design §5). Charles becomes
**tenant #1** (`user-charles`) and dogfoods the platform permanently.

---

## 2. Feature-parity map

Legend: **Equivalent** (works the same or better) · **Partial** (works, with
a documented difference) · **Gap** (not in the platform; intentional or
deferred).

| Capability | OpenClaw today | Quill Agent Cloud | Status |
|---|---|---|---|
| **Chat / orchestration** | Local agent loop, streaming | Orchestrator loop (SSE), per-tenant, budgeted | **Equivalent** |
| **Long-term memory** | `memory/*.md` + MEMORY.md, semantic recall | `agentcloud_memory` (pgvector + keyword fallback), `auto_recall` policy | **Equivalent** (embeddings staged, CUTOVER.md §2) |
| **Sub-agents** | Spawned local subagents | `agentcloud_jobs` (local or Cloud Run Jobs), same budget/refusal semantics, parent wake | **Equivalent** (durable backend = `cloudrun`, staged) |
| **Scheduling / heartbeats** | Cron + 15-min heartbeats, morning/EOD briefs | Per-tenant cron + one-shot schedules; SKIP-LOCKED claim; tick backend | **Partial** — see §3.1 (proactive push) |
| **Approvals / writes** | Quill `/queue` approval pattern | Same `/queue`; write tools are proposal-only, lane 1/2/3, audit-chained | **Equivalent** (this is the shared origin) |
| **Channels** | Telegram (main), iMessage bridge | Telegram + Google Chat via pairing codes; approval-gated | **Partial** — see §3.2 |
| **Tenancy / isolation** | Single machine, Charles-only | Per-user tenant, app-layer + Postgres RLS, isolation attack suite | **Equivalent+** (stronger) |
| **Budgets / metering** | Ad-hoc ($20 cap pattern) | Per-agent + per-tenant monthly caps, meters UI, rate limits | **Equivalent+** |
| **Per-tenant secrets** | Local env / files | `agentcloud_tenant_secrets` (KMS envelope) | **Equivalent+** (KMS staged, CUTOVER.md §6) |
| **Agent authoring** | Edit prompts/skills on disk | Agent Builder (CRUD, tool palette, templates, test console) | **Equivalent+** |
| **Skills / plugin tools** | Rich local skill library (gog, apple-*, etc.) | Curated tool registry (get_time, memory, 6 Quill reads, 5 approval-gated writes) | **Gap** — see §3.3 |
| **Machine-level exec / filesystem** | Full shell on the Mac | **None by design** | **Gap (intentional)** — §3.4 |
| **Files / workspace** | Local `~/.openclaw/workspace` | No general file workspace in-platform | **Gap** — §3.5 |
| **Image/video/music/web tools** | Generation + web fetch/search tools | Not in the platform tool registry today | **Gap (deferred)** — §3.3 |
| **Deliverable docs (Google Docs)** | `gog` CLI on the Mac | Not a platform tool (approval-gated write tools are Quill-scoped) | **Gap (deferred)** — §3.3 |

---

## 3. Honest gaps (flagged)

### 3.1 Proactive delivery (schedules/reminders) — Partial

Platform schedules **fire** correctly and run a real agent turn, but delivery
is the **passive `[system wake]`** model: the reply lands in the target
session and the user/agent sees it on the next turn — nothing yet *pushes* it
to Telegram/Chat/web proactively (KNOWN_ISSUES A3 #3, A4 #4, D #3). OpenClaw's
morning brief / EOD wrap / 15-min heartbeat all *proactively message*
Charles. **Gap:** a proactive-push consumer (Pub/Sub → channel send) is a
follow-up slice. Until then, scheduled work is best-effort-visible, not
push-delivered. *(visible-frustrating for the brief/heartbeat use case.)*

### 3.2 Channels — Partial (external ops pending)

Telegram + Google Chat are **code-complete and unit-tested** but dark until
external registration (BotFather `setWebhook`; Google Chat/Marketplace
verification) — CUTOVER.md §7–§9. No **iMessage** channel in-platform
(OpenClaw uses the Mac's iMessage bridge; that stays a personal, optional Mac
job per design §8). *(visible-frustrating pre-registration; iMessage is an
intentional out-of-scope.)*

### 3.3 Tool/skill breadth — Gap (deferred)

OpenClaw has a broad skill library (gog Google Workspace, Apple Notes/
Reminders, image/video/music generation, web fetch/search, meme/diagram
makers, etc.). The platform ships a **deliberately curated** registry:
`get_time`, memory tools, 6 read-only Quill tools, 5 approval-gated Quill
write tools. Anything outside that isn't available to a cloud agent yet.
**Gap:** new tools are additive (register in `app/tools/`, add to the catalog,
approval-gate writes) but each is a scoped piece of work with its own
security review. *(visible-frustrating for anyone expecting OpenClaw's full
toolbox on day one; intentional safety posture — curated tools + allow-lists
are the injection defense, design §6.)*

### 3.4 Machine-level exec / filesystem — Gap (intentional, permanent)

The platform has **no shell, no exec, no arbitrary filesystem** — this is the
core security win (design §5: "same agentic power where it's safe, none of the
machine-level blast radius"). Any workflow that depends on running commands on
a host does **not** move to the platform; it either stays on the Mac
(personal, optional) or is re-expressed as a curated tool + approval.
*(Not a bug — the whole point.)*

### 3.5 General file workspace — Gap

There is no per-tenant general file store/workspace in-platform (memory rows
are structured, not a filesystem). Workflows that read/write loose files in
`~/.openclaw/workspace` have no direct equivalent. *(visible-tolerable —
re-express as memory + approval-gated writes, or keep on the Mac.)*

---

## 4. Staged rollout

A deliberate, reversible ramp. Each stage has an exit criterion before the
next.

### Stage 0 — Deploy (no cutover)

Deploy the current image to prod on **default backends**. Web chat, Agent
Builder, budgets/meters, and approvals all work. OpenClaw is unchanged and
remains Charles's brain. **Exit:** `GET /health` green, web chat round-trips,
Agent Builder saves + test console works.

### Stage 1 — Dogfood (tenant #1, parallel)

Run `scripts/dogfood_seed.py` to provision `user-charles` with the two seeds +
the `dogfood` agent (CUTOVER.md §12). Do the external ops you want first
(embeddings, Cloud Run Jobs, Cloud Scheduler, KMS — CUTOVER.md §1–§6). **Use
it daily in parallel with OpenClaw.** Nothing is retired.
**Exit:** for a soak period, the canonical paths all work live — web chat, a
scheduled reminder, a sub-agent job, an approval-gated write, and (once
registered) a paired channel message — with no correctness surprises, and the
§3.1 proactive-delivery gap is either accepted or closed.

### Stage 2 — Limited

Register channels (CUTOVER.md §7–§9), flip `CHANNELS_ENABLED=true`, and route
a subset of Charles's real workflows to the platform (the ones that don't hit
the §3.3/§3.4/§3.5 gaps). Keep OpenClaw for everything that does.
**Exit:** the platform reliably handles its subset for a sustained period;
gaps that block real daily use are triaged (close, accept, or keep-on-Mac).

### Stage 3 — Full cutover (Charles's decision)

Only when Stages 1–2 have soaked cleanly: decide to retire OpenClaw as the
brain. Per design §8, the Mac's only remaining job becomes the optional
personal iMessage bridge. **Nothing in this codebase flips this** — it is a
conscious human decision (CUTOVER.md §13). Reversible in practice by keeping
OpenClaw installed until confidence is high.

---

## 5. What does NOT migrate (keep on the Mac or drop)

- Machine-level exec / shell workflows (§3.4) — permanent gap by design.
- The iMessage bridge — stays a personal, optional Mac job (design §8).
- Loose-file workspace workflows (§3.5) — re-express or keep local.
- Skills without a platform tool equivalent (§3.3) — until each is ported.
- Proactive brief/heartbeat *push* (§3.1) — until the push consumer ships;
  the schedules themselves run, they just don't push proactively yet.

---

*Phase E deliverable. Parity is honest, gaps are flagged with severity, and
the rollout is staged and reversible. The retire-OpenClaw switch is Charles's
alone.*
