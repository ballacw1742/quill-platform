# ADK Task-Agent Runtime — implementation notes & live-install follow-up

Implements ADK_AGENTS_DESIGN.md §2 (real Google ADK task-agents).

## What's live now
- `app/adk/base.py` — `TaskAgentRunner` interface + `TaskContext` / `TaskResult`
  (token/cost accounting fields feeding budgets/meters).
- `app/adk/registry.py` — curated ADK tool registry:
  - **read** — Quill read tools (reused from `app/tools/quill.py`).
  - **deliverable** — `generate_deliverable` (Doc/Sheet → Drive) + `web_fetch`.
  - **memory** — `memory_save` / `memory_search` (reused).
  - **write** — approval-gated Quill writes (reused from `app/tools/quill_writes.py`),
    routed through the existing `/v1/approvals` seam. NO raw shell.
  - Governance filter: `adk_tool_specs(..., allow_writes=False)` and
    `effective_allowlist(..., allow_writes=False)` drop **write** tools for an
    unapproved / read-only task-agent (structural read-only enforcement).
- `app/adk/runner.py` — `AdkAgentRunner`:
  - Conforms to `TaskAgentRunner` (`run(task, context) -> TaskResult`).
  - Same budget gate (agent + tenant monthly caps) as the chat loop; a SHARED
    agent used by user B is metered under B's tenant.
  - Emits audit-chain events (`task.started`, `task.completed`/`task.failed`,
    `budget.exceeded`) via `app/events`, and meters tokens/cost via
    `app/budget.record_usage` — identical accounting to a chat turn.

## google-adk install status
`google-adk` is an OPTIONAL dependency (see `requirements-adk.txt`). On this
dev/CI host it is NOT installed, so `_adk_available()` returns False and the
runner drives the same tools/accounting under the platform `ModelProvider`
tool-loop. This is a real implementation of the feature (tools, approvals,
audit, governance all exercised), NOT a stub.

### To go fully-live with google-adk
1. `pip install -r requirements-adk.txt` (adds `google-adk`).
2. The runner auto-selects the ADK code path when `google.adk` is importable
   (`_adk_available()`), building `google.adk.agents.Agent` + `Runner`. The
   tool contracts and pricing table are shared, so the loop body is identical.
3. Live Google Drive authoring for `generate_deliverable`: set `DRIVE_ENABLED`
   once the platform Drive service is wired into agent-cloud. Until then the
   tool produces a durable local deliverable record (`drive.mode='local'`),
   so the read-only → deliverable flow works end-to-end without creds. The
   `_author_to_drive` seam raises `NotImplementedError` (caught → local
   fallback) so the feature never fakes a Drive success.

## Follow-ups (tracked)
- [ ] Wire real Google Drive/Docs/Sheets authoring behind `DRIVE_ENABLED`.
- [ ] Once `google-adk` is installed in prod, add an integration test that runs
      a task under `google.adk.runners.Runner` (currently provider-backed).
