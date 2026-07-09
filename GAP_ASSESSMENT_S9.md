# GAP_ASSESSMENT_S9.md — §9 "Local-First Agentic Execution Platform" vs. the Codebase

**Date:** 2026-07-08 · **Repo:** `quill-platform` @ `main` / `0420f87` · **Mode:** READ-ONLY assessment
**Author:** gap-assessment sub-agent (Axe) · **Source of truth for the target:** §9 of the Google Doc `1ljQRO1w5-4g1kNUsyNRWgDy7mQGOaLzMAW_MbpoVEyU` (exported via `gog`, read in full).

> Method note: every "exists" claim below cites a file I actually read. Every "missing" claim
> is backed by a grep/read that came up empty (called out inline). I did not modify any file.

---

## 0. Executive summary

The §9 vision is **more real than aspirational**, and that is the surprising, load-bearing
finding. The two hardest architectural claims — (a) §9.2 "the data layer is decoupled from the
operating layer; users change representation, not substance" and (b) §9.6 "an agent is data not
code, so local re-hosting is tractable" — are **substantially true in the code today**, not slideware:

- **§9.2 is structurally enforced, not merely intended.** The agent-cloud operating layer
  (`agentcloud_*` tables) and the Quill foundational data layer (`api/app/models*.py`) are
  physically separate table families reached through **different processes over HTTP**. A
  user-authored cloud agent has **no direct write path** into Quill records: its write tools only
  `POST /v1/approvals` (`agent-cloud/app/approvals.py`), and the *only* code that mutates a Quill
  business object is `api/app/services/agentcloud_actions.py::execute_agentcloud_action`, called
  from `execute_approval` **after a human approval is recorded**. There is no `agentcloud_actions`
  import or `Project(...)` / `Deal(...)` constructor anywhere in `agent-cloud/`.
- **§9.1 (agents-as-a-product) is built to our-internal-grade,** with a real self-serve authoring
  UI (`web/app/assistant/builder/page.tsx`) over a CRUD API (`agent-cloud/app/agents.py`). It is
  usable but curated/narrow (5 write tools, 3 templates) — user-grade breadth is the gap.
- **§9.4 (HITL gated by risk) is the most mature piece.** The Lane 1/2/3 + TrustTier model is
  fully coded in `api/app/enums.py`, `runtime/runtime/lane_router.py`, and
  `api/app/services/approvals.py`. The one live safety caveat: agent-cloud pins **every** proposed
  write to Lane 2 (`agent-cloud/app/approvals.py`), so the risk-graded auto-execute promised by
  §9.4 is *engine-capable but not yet wired for cloud-authored agents*.
- **§9.5 (local-first, near-zero token cost) is astonishingly close on portability.** Every GCP
  dependency is already behind a config switch **whose default is the local/off variant**:
  `MODEL_PROVIDER` (anthropic|vertex), `EVENT_BUS` (inline|pubsub), `JOBS_BACKEND` (local|cloudrun),
  `SCHEDULER_BACKEND` (loop|…), `SECRETS_BACKEND` (plaintext-dev|kms), `DATABASE_URL`
  (sqlite|postgres). The remaining local-first gap is **local model inference** (no `ollama`/
  `vLLM`/`llama.cpp` provider exists) — that is the one true net-new build for §9.5.

Bottom line: §9 is not a rewrite. It is (1) breadth work on the tool registry, (2) wiring the
already-built risk-gated auto-execute for cloud agents, (3) a local-inference provider, and
(4) a proactive-delivery consumer. The architecture the vision depends on is already in the tree.

---

## 1. CURRENT STATE per §9 subsection (with file evidence)

### 9.1 — Agents-as-a-product, built by users
**Exists (our-internal-grade, trending user-grade):**
- **Agent = one DB row.** `agent-cloud/app/models.py::AgentDef` (table `agentcloud_agents`) stores
  `system_prompt`, `model`, `tools` (JSON), `memory_policy`, `budget_monthly_usd`, `enabled`. The
  class docstring literally reads *"An agent is data, not code (design doc §3.3)."*
- **Full CRUD authoring surface.** `agent-cloud/app/agents.py` implements
  `create_agent`/`update_agent`/`delete_agent` (soft-delete), slug/prompt/tool/model/budget
  validation, a `tool_catalog()` palette and 3 `templates()` (research-assistant, ops-analyst,
  project-copilot).
- **Self-serve UI.** `web/app/assistant/builder/page.tsx` — form + tool palette + template picker
  + **live test console** (SSE against the saved agent). Workspace toggle (personal|org); the JWT
  bridge injects `tenant_id` so it never leaks into the client.
- **"Evolve as workflow changes" is real:** `update_agent` emits an `agent.updated` event and
  patches the row in place; seeds are protected (can't disable/delete).

**Honest limitation:** curated, not open-ended. Tools are limited to a fixed registry (see 9.3);
"routine as editing a spreadsheet" is true for prompt/model/memory/budget/tool-selection, but a
user cannot yet author *new tool capabilities* from the UI.

### 9.2 — The layered separation (the load-bearing idea)
**Exists and is structurally enforced** (full audit in §3):
- **Two physically separate table families.** Operating layer = `agentcloud_*`
  (`agent-cloud/app/models.py`). Foundational data layer = `approval_items`, `projects`, `deals`,
  `requests`, etc. (`api/app/models.py`, `api/app/models_projects.py`, `models_pipeline.py`,
  `models_requests.py`). Different services, different DBs-in-principle, HTTP between them.
- **No direct write path from operating→foundational.** `agent-cloud/app/approvals.py` write path
  = validate args → `POST /v1/approvals` (`X-Agent-Secret`) → persist an `agentcloud_proposals`
  row → return `"pending_approval"` to the model. It **never** constructs a Quill ORM object.
- **The single mutation seam** is `api/app/services/agentcloud_actions.py::execute_agentcloud_action`,
  invoked only by `api/app/services/approvals.py::execute_approval`, itself gated by lane/approval.

**"Change representation, not substance" reading:** a user reshaping their agent (prompt, tool
mix, workflow) changes only `agentcloud_agents` rows and their session/memory — never a Quill
record. Substance changes only travel through the approval executor.

### 9.3 — A project is a stream of text through a digital+physical medium
**Exists (dispatch machinery is built; breadth is narrow):**
- **The "stream of text" engine** is the dispatcher family:
  `runtime/runtime/{triage,classification,contract,contract_review,contract_draft,estimator}_dispatcher.py`.
  `triage_dispatcher.py` is a crash-safe, idempotent, cursor-based daemon that watches an event
  source (file JSONL in dev; "Procore webhooks" in prod per its own docstring) and runs an agent
  chain per event.
- **Emails/texts/clicks as automatable channels:** `agent-cloud/app/channels/` + `CHANNELS.md`
  implement Telegram + Google Chat inbound/outbound via `agentcloud_channel_links` pairing
  (`models.py::ChannelLink`). These are the "text through a medium" I/O ports.
- **Reads + writes of the stream:** 6 read-only Quill tools + 5 approval-gated write tools
  (`agent-cloud/app/tools/quill.py`, `quill_writes.py`; catalog in `agents.py::_GROUPS`).

**Honest limitation:** the "every digital form of communication … automatable" ambition is
partial. Email send, arbitrary web/system clicks, and document authoring are **not** platform
tools (confirmed by `agent-cloud/MIGRATION.md §3.3` which explicitly lists gog/email/web/gen tools
as deferred gaps). The engine generalizes; the tool breadth doesn't cover it yet.

### 9.4 — Human-in-the-loop only for critical-risk decisions
**Exists (most mature subsystem):**
- **Lane model:** `api/app/enums.py::Lane` = AUTO(1)/SINGLE(2)/DUAL(3); `TrustTier` =
  tier-0-mandatory / tier-1-spotcheck / tier-2-auto — exactly the doc's vocabulary.
- **Risk-graded routing:** `runtime/runtime/lane_router.py::route_lane` computes
  `final_lane = strictest(agent_default, low_confidence, cost_impact, schedule/critical_path,
  safety)`, with dual-approval escalation on safety∧(cost∨schedule) or multi-approver. This is
  §9.4's "gated by risk, not by habit" as literal code.
- **Auto-execute for trusted, low-risk:** `api/app/services/approvals.py` — on create, if
  `item.lane == Lane.AUTO` it calls `execute_approval` immediately (line ~121); Lane 2/3 require a
  recorded human decision (`decide_approval`, passkey-minted action-assertion JWT with replay
  protection, `api/app/routes/approvals.py::decide`).
- **TrustTier promotion path modeled:** `api/app/models.py::AgentRegistration.trust_tier` +
  `default_lane` per agent.

**Honest limitation / live safety caveat:** cloud-authored agents do **not** yet get the
risk-graded lane. `agent-cloud/app/approvals.py::create_proposal` hard-codes `"lane": 2` with the
comment *"always single-approver; never auto-execute (APPROVALS.md §3)."* So §9.4's "human
touch-points shrink toward zero" is engine-ready but **deliberately fixed at Lane 2** for the
agent-cloud path today. Promotion to Lane 1 for tier-2 cloud agents is unbuilt.

### 9.5 — On-prem, closed-loop, near-zero token cost
**Partially exists (portability yes; local inference no):**
- **Every GCP dependency is config-switched with a local default** (`agent-cloud/app/config.py`):
  `MODEL_PROVIDER=anthropic` (not vertex), `EVENT_BUS=inline` (not pubsub — `events.py::InlineBus`
  vs `PubSubBus`), `JOBS_BACKEND=local` (asyncio task, not Cloud Run Job — `jobs.py`),
  `SCHEDULER_BACKEND=loop` (in-process, not Cloud Scheduler HTTP), `SECRETS_BACKEND=plaintext-dev`
  (not kms — `secrets.py` envelope path), `DATABASE_URL=sqlite+aiosqlite://…` default with a
  Postgres variant. The whole stack **already boots with zero GCP services** (that's how the test
  suite runs).
- **Data-layer portability:** models are dialect-portable — `JSONVariant = sa.JSON().with_variant(
  JSONB(),"postgresql")`, `BigIntPK` variant, sqlite `create_all` for tests
  (`agent-cloud/app/models.py`; `api/app/models.py::JSONType`). `pgvector` is the only
  Postgres-only feature and it already has a **keyword-search fallback** on sqlite
  (`MemoryRow` docstring + `MIGRATION.md`).

**The one true gap:** local model **inference**. `agent-cloud/app/providers/__init__.py` only
knows `anthropic` (Anthropic API) and `vertex` (GCP) — both are metered cloud endpoints. There is
**no** local-inference provider (grepped: no `ollama`, `vllm`, `llama.cpp`, `lmstudio`, `local`
provider). §9.5's "inference on local hardware, pay only for electricity" requires a new
`ModelProvider` implementation. Embeddings have the same shape: `EMBEDDING_PROVIDER=gemini|none`
(`config.py`), so local embeddings are a parallel small gap (the `none` fallback already exists).

### 9.6 — Reconciling the tension (cloud on-ramp, local destination)
**Exists as an explicit, documented strategy:**
- `agent-cloud/MIGRATION.md` and `CUTOVER.md` already codify a staged, reversible ramp
  (Stage 0 deploy → 1 dogfood → 2 limited → 3 full), with an honest parity map. §9.6's build
  order is literally the doc's rollout plan.
- The §9.6 mechanism ("agent is data + layered separation makes local migration tractable") is
  validated by §9.2/§9.5 above: because agents are rows and the GCP services are swappable
  defaults, "re-host the same agent definitions + same schema on local hardware" is a **config +
  one-provider** exercise, not a rewrite. The code backs the claim.

---

## 2. GAPS per subsection — (a) net-new build · (b) harden/refactor · (c) pure vision/no-code

### 9.1 Agents-as-a-product
- **(b) Harden:** builder UX is single-user/our-grade — no per-user agent versioning/history,
  no diff/rollback, no publish/share, no non-owner author roles. (`agents.py` has no version
  column; `AgentDef` has no `version`.)
- **(a) Net-new:** "author new *tools*/capabilities from the UI" — today tools are a fixed
  Python registry (`app/tools/`). User-authored tools = a real net-new subsystem (sandboxing,
  security review) — arguably intentionally *not* user-authorable for safety.
- **(c) Vision:** "as routine as editing a spreadsheet" is a UX-maturity target, largely reachable
  by (b).

### 9.2 Layered separation
- **(c) Mostly vision-confirmed:** the separation is real (see §3). No net-new build required for
  the core claim.
- **(b) Harden:** the two "mirror vocabulary" lists (`agent-cloud/app/approvals.py` VALID_PHASES/
  VALID_DEAL_STAGES vs. api-side `models_projects.py`/`models_pipeline.py`) are **hand-synced**
  ("Kept in sync by the A6 contract tests"). That's a coherence risk if they drift — candidate for
  a generated shared contract (LESSONS #1 territory).

### 9.3 Stream-of-text
- **(a) Net-new tools:** email send, generic web/system click automation, document authoring
  (Docs/Drive) as approval-gated tools. Each is a scoped, security-reviewed addition
  (`MIGRATION.md §3.3`).
- **(a) Net-new ingress:** the prod `WebhookEventSource` (Procore etc.) that `triage_dispatcher.py`
  anticipates but doesn't ship (dev uses a file source).
- **(b) Harden:** proactive delivery — schedules fire but only via passive `[system wake]`; a
  push consumer is missing (see 9.4/`MIGRATION.md §3.1`).

### 9.4 HITL gated by risk
- **(a) Net-new (small, high-leverage):** wire the risk-graded lane into the agent-cloud path.
  Today `create_proposal` pins `lane=2`. To honor §9.4 for cloud agents: consult
  `AgentRegistration.trust_tier`/`route_lane` semantics so a tier-2 cloud agent's low-risk write
  can be Lane 1 auto-execute (with audit), while money/contract/irreversible stays Lane 2/3.
- **(b) Harden:** a TrustTier *promotion* mechanism (auto-promote on a clean track record) is
  modeled (`trust_tier` column) but I found no promotion logic (grepped `promote` — only the enum/
  column; no state machine). Promotion is manual/unbuilt.

### 9.5 Local-first
- **(a) Net-new (the headline):** a **local-inference `ModelProvider`** (ollama/vLLM/llama.cpp)
  behind `MODEL_PROVIDER=local`, plus a local **embeddings** path behind `EMBEDDING_PROVIDER=local`.
- **(a) Net-new:** an on-prem packaging/deploy artifact (compose/k8s) that runs the inline/local/
  loop/plaintext(→a local KMS-equivalent) profile as a supported product SKU.
- **(b) Harden:** promote `SECRETS_BACKEND=plaintext-dev` to a real on-prem KEK (e.g. HashiCorp
  Vault / age / TPM) so local ≠ plaintext-on-disk.
- **(c) Vision:** "cost collapses to electricity" — an economic claim that follows automatically
  once local inference lands.

### 9.6 Reconciliation
- **(c) Pure vision / already-documented:** `MIGRATION.md`/`CUTOVER.md` cover it. No code gap; it
  is the sequencing narrative for everything above.

---

## 3. THE HARD ONE — §9.2 layered-separation audit (is it real?)

**Verdict: REAL, and structurally enforced — not aspirational.** Evidence chain:

1. **Two separate table families, two services.**
   - Operating layer: `agent-cloud/app/models.py` — `agentcloud_tenants/agents/sessions/messages/
     memory/events/jobs/schedules/proposals/channel_links/usage/rate_limits/tenant_secrets`.
   - Foundational data layer: `api/app/models.py` + `models_projects.py` + `models_pipeline.py` +
     `models_requests.py` — `approval_items`, `projects`, `deals`, `accounts`, `requests`, etc.
   - They are reached by **different FastAPI apps** communicating over HTTP with `X-Agent-Secret`.

2. **"Agent is data, not code" is literally true.** `AgentDef` (docstring: *"An agent is data, not
   code (design doc §3.3)"*) holds the prompt/model/tools/memory/budget as columns. The
   orchestrator (`agent-cloud/app/orchestrator.py::_prepare`) loads that row and drives a generic
   tool loop; there is no per-agent Python class. Creating/altering an agent is a row write
   (`agents.py`), not a code deploy. **This is the mechanism §9.6 relies on for local migration.**

3. **Can a user-authored agent mutate the operating layer without touching foundational records?**
   **Yes — that is exactly the designed behavior.** A user editing their agent, sessions, or memory
   writes only `agentcloud_*` rows. None of `create_agent`/`update_agent`/`orchestrator`/`memory`
   touch a Quill business table (verified: no import of `models_projects`/`models_pipeline` and no
   Quill ORM constructor anywhere under `agent-cloud/`).

4. **Can a user-authored agent mutate foundational records directly? No.** The only write path is:
   `quill_writes` tool → `approvals.create_proposal` → `POST /v1/approvals` → (human approves) →
   `api/app/services/approvals.py::execute_approval` → `agentcloud_actions.execute_agentcloud_action`.
   That executor is the **sole** place a `Project`/`Deal`/`RequestRecord` is mutated on behalf of a
   cloud agent, and it **re-validates every arg** (belt #2) before mutating, mirroring the human
   PATCH-route side effects (e.g. deal "won" → prospect account promoted to customer).

5. **Coherence guarantees on the foundational layer:** audit chain (`AuditLogEntry` hash-chained,
   `AuditChainVerification`, `record_event_with_mirror`), litigation hold, idempotency
   (`agentcloud_proposals.idempotency_key`, race-safe conditional `UPDATE WHERE status='pending'`
   in `finalize_proposal`), and tenant isolation (app-layer filter + Postgres RLS — `TENANCY.md`).

**The one real weakness in the separation** (honesty per the brief): the arg-vocabulary contracts
are **duplicated by hand** on both sides — `agent-cloud/app/approvals.py` re-declares
`VALID_PHASES`, `VALID_DEAL_STAGES`, `VALID_ENTRY_TYPES` with a comment that they are "kept in sync
… by the A6 contract tests," while the canonical copies live in `api/app/models_projects.py` /
`models_pipeline.py`. Drift here wouldn't corrupt data (the api-side executor re-validates and
rejects), but it *would* cause silent proposal failures. This is a maintainability seam, not a
data-integrity hole — but it's the thing most likely to bite as the write-tool surface grows.

**Net:** §9.2's "change representation, not substance" is not a slogan bolted onto the code; it is
the actual control-flow topology. The load-bearing claim holds.

---

## 4. §9.5 LOCAL-FIRST feasibility sketch (high-level)

**Thesis: ~80% portable today by config; the missing 20% is local inference + on-prem packaging.**

### 4.1 What's already portable (config switch, local default)
| Concern | Cloud impl | Local switch (already in code) | Evidence |
|---|---|---|---|
| Event bus | Pub/Sub (`PubSubBus`) | `EVENT_BUS=inline` (`InlineBus`, default) | `agent-cloud/app/events.py` |
| Sub-agent jobs | Cloud Run Jobs | `JOBS_BACKEND=local` (asyncio, default) | `agent-cloud/app/jobs.py` |
| Scheduler | Cloud Scheduler HTTP tick | `SCHEDULER_BACKEND=loop` (in-proc, default) | `config.py`, `scheduler.py` |
| Secrets | Cloud KMS envelope | `SECRETS_BACKEND=plaintext-dev` (default) | `agent-cloud/app/secrets.py` |
| Data store | Cloud SQL (Postgres+RLS+pgvector) | `DATABASE_URL=sqlite…` + keyword-search memory fallback | `models.py`, `db.py`, `memory.py` |
| Model auth | Vertex (IAM) | `MODEL_PROVIDER=anthropic` (API key) | `providers/__init__.py` |

The stack **already runs with none of these GCP services** (that's the test/dev profile). So the
"same schema + same agent rows on local hardware" claim of §9.6 is verified: it is a deploy
profile, not a rewrite.

### 4.2 GCP lock-in points and their local equivalents
- **Pub/Sub** → local: NATS / Redis Streams / RabbitMQ, or just the existing `InlineBus` for a
  single-node on-prem box. *(A local durable bus adapter is a small new backend alongside `PubSubBus`.)*
- **Cloud SQL** → local: self-hosted Postgres + pgvector (fully portable; models already dialect-safe).
- **Vertex** → local: **new** `MODEL_PROVIDER=local` provider (see 4.3). This is the only hard one.
- **Secret Manager / KMS** → local: HashiCorp Vault, `age`, or a TPM/HSM-backed KEK; replace the
  `kms` backend's wrap/unwrap with a local KEK. The envelope structure already exists.
- **Cloud Run Jobs** → local: the `local` asyncio backend works for a single node; for isolation,
  a container/subprocess runner adapter.
- **Cloud Scheduler** → local: the `loop` backend already covers it; a systemd timer/cron is an
  alternative.

### 4.3 The one net-new: local inference
- Implement `app/providers/local_*.py` conforming to `ModelProvider`
  (`agent-cloud/app/providers/base.py` — `complete()` + `stream()` + `input/output_tokens`),
  wired via `get_provider("local")`. Candidate engines: **ollama** (easiest, OpenAI-compatible
  HTTP), **vLLM** (throughput), **llama.cpp** (smallest footprint). Because the orchestrator is
  provider-agnostic, this is genuinely a **one-file add + a `MODEL_PROVIDER` branch**.
- Pricing table (`providers/pricing.py`) needs a `$0` (electricity-only) entry so budgets/meters
  read ~0 — which is the concrete realization of §9.5's "near-zero token cost."
- Local **embeddings** mirror this (`EMBEDDING_PROVIDER=local`), and the `none` fallback already
  keeps memory working without them.

### 4.4 The "AI laptop per user" (§9.5)
Maps cleanly onto the existing per-tenant model: one on-prem box = one tenant's `agentcloud_*`
schema + local Postgres + local inference; the "laptop" is a thin client hitting the local
orchestrator (same web UI, `AGENTCLOUD_URL` pointed at localhost). No architectural change — it's
the single-tenant deployment of the multi-tenant design.

---

## 5. PHASED PLAN (ordered; dependencies + parallelism flagged)

> LESSONS.md #1/#10 honored: I mark where a **shared contract must be authored first** and where
> parallel sub-agents on the same seam are forbidden. Effort is rough (S ≤2d, M ~1wk, L ~2–3wk).

### Phase 0 — De-risk the coherence seam (do first; unblocks safe growth) — **S**
- Replace the hand-synced arg vocabularies with a **single generated contract** consumed by both
  `agent-cloud/app/approvals.py` and `api/app/services/agentcloud_actions.py` (§3 weakness).
- **Sequential, single owner** (it's a shared contract — do NOT parallelize). No dependency.

### Phase 1 — §9.4 risk-graded lane for cloud agents (highest product leverage) — **M**
- Author the **lane-decision contract** (inputs: agent trust_tier, action class, confidence,
  money/irreversible flags → output lane) as a shared artifact FIRST.
- Then, in `agent-cloud/app/approvals.py::create_proposal`, replace the hard-coded `lane=2` with a
  call that respects `AgentRegistration.trust_tier` + a per-action risk class; keep money/contract/
  irreversible at Lane 2/3.
- Add the **TrustTier promotion** state machine (clean-track-record → tier-2) — api-side.
- **Dependency:** Phase 0 (shares the proposal path). **Sequential** on the approvals path;
  the promotion state machine can proceed in parallel *only* behind the authored contract.

### Phase 2 — §9.5 local inference provider (the on-prem enabler) — **M/L**
- New `MODEL_PROVIDER=local` provider + `$0` pricing entry + `EMBEDDING_PROVIDER=local`.
- **Fully parallel** with Phases 0/1 (touches `providers/` only — no shared contract with the
  approvals path). This is the single most vision-defining build for §9.
- **Dependency:** none on 0/1; downstream Phase 4 depends on it.

### Phase 3 — §9.3 tool breadth + prod ingress (parallelizable by tool) — **L**
- Add approval-gated tools one at a time (email send → Docs authoring → web/system automation),
  each with its own security review; add the prod `WebhookEventSource` for `triage_dispatcher.py`.
- Add the **proactive-push consumer** (event → channel send) to close `MIGRATION.md §3.1`.
- **Parallel-safe** *only because each tool is independent* (different registry entries, no shared
  data shape) — the exact condition LESSONS #10 permits. The push consumer is sequential-ish (it
  consumes the event bus contract).
- **Dependency:** Phase 0 for any new *write* tool (shares the proposal contract).

### Phase 4 — §9.5 on-prem packaging SKU + local KEK (the destination) — **L**
- Compose/k8s profile running inline/local/loop backends + local Postgres + local inference;
  replace `plaintext-dev` secrets with a real on-prem KEK (Vault/age/TPM); add a local durable-bus
  adapter alongside `InlineBus` if multi-node.
- **Dependency:** Phase 2 (needs local inference to be a real product). Runs after 1–3 soak.

### Phase 5 — §9.1 authoring maturity (user-grade polish) — **M**
- Agent versioning/diff/rollback, publish/share, non-owner author roles.
- **Parallel** with Phase 3/4 (UI + `agents.py` only). No cross-service contract.

**Parallelization summary:** Phase 2 and Phase 5 can run alongside the 0→1→3→4 spine. The **only**
sequential-critical, contract-first steps are Phase 0 (coherence seam) and Phase 1 (lane contract)
— because both touch the shared proposal/approval boundary that LESSONS #1 warns about.

---

## 6. IMMEDIATE NEXT STEP (single highest-leverage first move)

**Phase 1's precondition: author the risk-graded lane contract and wire it into the agent-cloud
proposal path — but do Phase 0 (the generated shared arg-vocabulary contract) in the *same* change
because they touch the same seam.**

Concretely, the first move is a **short design spike + contract artifact** (not code-in-anger):
define the mapping `(agent.trust_tier, action_class, risk_flags) → lane` and the shared
phase/stage/entry-type vocabulary as **one authoritative file both services read**, then flip
`agent-cloud/app/approvals.py::create_proposal` off its hard-coded `lane=2`.

Why this first: it is the smallest change that (a) makes §9.4's "human attention only where risk
justifies it" *true for user-authored cloud agents* — the thing that makes agents-as-a-product
actually autonomous — and (b) simultaneously closes the one genuine integrity/maintainability
weakness found in the §9.2 audit. It is high-leverage, low-surface, and it unblocks the
autonomy story that every other §9 subsection assumes.

*(Local inference (Phase 2) is the more spectacular build, but it can proceed in parallel and does
not gate the autonomy that §9.1/9.3/9.4 depend on. The lane contract does.)*

---

*Assessment complete. Read-only: no code/config/docs modified, no git operations performed.*
