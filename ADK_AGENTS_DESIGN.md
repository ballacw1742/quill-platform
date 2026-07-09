# ADK Task-Agents + Cross-Platform Sharing + Workflow-Assignment Governance

**Date:** 2026-07-09 · **Author:** Axe · **Status:** Design for build (Charles greenlit, merge-live)
**Decision inputs (Charles, 2026-07-09):**
- Real **Google ADK task-agents** created via the Builder — bots that perform real tasks, not chatbots.
- Agents **shareable across the platform** with other users. **This is an INTERNAL tool** → cross-tenant sharing is acceptable and desired (reverses strict isolation for shared agents only).
- Users **assign agents into the work process**; assignment updates the **workflow definition (DATA, not raw source)** — the §9.2 "change representation, not substance" model.
- **Governance:** any user can *create* an agent and *suggest* a workflow assignment; **only owners approve**. Until approved, the agent is **read-only + deliverable-generation** (can produce deliverables, has read access, CANNOT change workflows/code/app state).
- "code" = **workflow-definition data** (stage→agent mapping), NOT source commits.
- Build end-to-end AND **merge live** tonight, gated on passing tests + E2E smoke.

---

## 1. Agent kinds

Extend `AgentDef` (additive columns, no destructive change):
- `agent_kind: str` default `"assistant"` — one of `assistant` (today's Claude chat/tool-loop) | `adk_task` (new: Google ADK task-agent).
- `runtime: str` default `"claude"` — `claude` | `adk`. ADK task-agents run via the ADK runtime (google-adk), not the Claude tool loop.
- `owner_user_id: str` — creator (for suggest/approve attribution).
- `visibility: str` default `"private"` — `private` (creator only) | `shared` (all platform users, internal-tool sharing) .
- `approval_state: str` default `"draft"` — `draft` | `suggested` | `approved` | `rejected`. Governs whether the agent may hold a live workflow assignment.

ADK task-agent definition adds:
- `adk_config: JSON` — ADK agent spec: instruction, tools (from a curated ADK tool registry), model (Vertex Gemini/Claude via ADK), sub-agents, output schema.

## 2. Google ADK runtime (real, not pattern)

New service module `agent-cloud/app/adk/` (or reuse the existing ADK specialist-agent service pattern in quill-adk-agents):
- Add `google-adk` dependency.
- `AdkAgentRunner` conforming to a shared `TaskAgentRunner` interface: `run(task, context) -> TaskResult` with tool-calls, token/cost accounting (feeds budgets/meters), and audit-chain events.
- Curated **ADK tool registry** (task tools): Quill read tools (free), deliverable-generation tools (Docs/Sheets authoring to Drive), web-fetch, memory — and **approval-gated write tools** that route through the existing `/v1/approvals` seam. NO raw shell.
- ADK task-agents are invoked (a) directly by a user to produce deliverables, and (b) by the dispatcher when assigned to a workflow stage AND approved.

## 3. Sharing (internal cross-tenant)

- `visibility="shared"` agents are readable/usable by ALL platform users. Implemented as a **platform-scope** read path that bypasses per-tenant RLS *only for shared agents* (explicit, audited), while private agents keep strict tenant isolation.
- A shared agent used by user B runs under B's budget/meters; writes still route to B's approval queue. Sharing exposes the DEFINITION, not the creator's data.
- New `agentcloud_agent_shares` is unnecessary for "share with everyone"; `visibility` column suffices for internal-all. (Granular per-user shares = future.)

## 4. Workflow assignment = data, governed

New table `agentcloud_workflow_assignments`:
- `assignment_id, workflow_id (chain_id), stage_key, agent_id, owner_tenant_id, suggested_by_user_id, state (suggested|approved|rejected|retired), approval_item_id, created_at, approved_by, approved_at`.
- The chain loader (`runtime/runtime/chains.py`) gains a **data overlay**: base chains stay in code; an *approved* assignment row can override/insert which `agent_id` runs at a given `stage_key`. Unapproved assignments are inert (never affect dispatch).

### Governance flow (maps onto existing Lane/HITL)
1. User creates ADK agent → `approval_state="draft"`.
2. User **suggests** assigning it to `workflow_id/stage_key` → creates an `agentcloud_workflow_assignments` row `state="suggested"` AND an **approval item** of new action type `workflow_assignment` (TargetSystem `workflow`), lane forced to **owner-approval** (Lane 3-style: only `owner` role can decide — NOT the trust-graded auto lane; workflow/code changes are always human-owner-gated regardless of agent trust).
3. **Only owners approve** (`role=owner` check in the decide path). Approve → assignment `state="approved"`, chain overlay picks it up, dispatcher runs the agent at that stage. Reject → `state="rejected"`, agent stays read-only.
4. **Until approved**, the agent still works: user can invoke it to **generate deliverables** and it has **read access**; it CANNOT mutate workflows/app state (its write tools remain approval-gated per normal, and it holds no live assignment).

### Safety invariants (non-negotiable)
- A `workflow_assignment` approval is **owner-only** and can **never** auto-execute regardless of agent trust_tier. (Extends Phase 1's rule: money/contract/irreversible + now workflow/code changes = always human-gated.)
- Unapproved agent = zero workflow/app-state mutation. Enforced structurally: no assignment row in `approved` state → chain overlay ignores it.
- All assignment approvals audit-chained (hash chain) like every other approval.

## 5. UI (Agent Builder + assignment)

`web/app/assistant/builder`:
- Agent-kind toggle: **Assistant** vs **Task agent (ADK)**. ADK mode surfaces the ADK config (instruction, ADK tool palette, output schema).
- **Share toggle** (private ↔ shared with platform).
- **"Assign to workflow"** panel: pick workflow + stage → **Suggest assignment** (any user). Shows assignment state (draft/suggested/approved/rejected).
- **Owner view:** pending workflow-assignment approvals in the existing `/queue`, owner-only approve/reject with a clear "this changes a live workflow" warning.
- Unapproved agents show a "Read-only — deliverables only" badge; a "Use to generate deliverable" action always available.

## 6. Build order (single coordinated owner for the shared seam)
1. Data model + migration (additive columns + assignments table).
2. ADK runner + curated ADK tool registry.
3. `workflow_assignment` approval action + owner-only decide + chain overlay loader.
4. Sharing read-path (visibility=shared).
5. UI wiring.
6. Tests + E2E smoke: create ADK agent → generate deliverable (unapproved, read-only) → suggest assignment → owner approve → dispatcher runs agent at stage → verify workflow overlay live; verify a non-owner CANNOT approve; verify unapproved agent cannot mutate workflow.
7. Merge live (gated on green tests + smoke).
