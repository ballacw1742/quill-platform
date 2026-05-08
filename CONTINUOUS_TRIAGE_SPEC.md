# Continuous Triage + Live Drafts — Spec (Quill v3 Phase F.1)

**Goal:** When a new RFI / submittal / DFR / PO event arrives, the appropriate agent runs immediately in the background, and the queue item already contains a draft response or recommendation by the time Charles taps into the queue. No "waiting for the agent."

This works because Tier 4 makes Sonnet 4.6 throughput effectively free at our project's volume (~50 RFIs/week peak ≈ 7 inferences/day = $0.50/day).

## Architecture

```
Source events (mock-data feeders or real Procore webhooks)
       │
       ▼
┌──────────────────────────────────────────────────────┐
│  TriageDispatcher (new daemon in runtime/)          │
│  - Subscribes to event stream (filesystem watcher in │
│    dev; Procore webhooks in prod via the API)        │
│  - Looks up the right agent for each event class     │
│  - Runs the agent (with prompt cache hit = fast)     │
│  - Submits the draft to the Approval Queue           │
│  - Records audit event                               │
└──────────────────────────────────────────────────────┘
       │
       ▼
Approval Queue (already exists — Phase 1)
       │
       ▼
Web UI shows the queue item WITH the draft pre-populated
Telegram bot push on new high-priority items
```

## Event → Agent mapping

| Event class | Agent dispatched | Lane |
|---|---|---|
| `rfi.created` | rfi-triage → rfi-drafter (chained) | 2 |
| `submittal.created` | submittal-triage → submittal-spec-validator (chained) | 2 |
| `dfr.posted` | dfr-synthesizer | 2 |
| `po.update` (vendor email, ship-date change) | procurement-watch | 2 (warn/alert/critical) or 1 (on_track) |
| `change_order.draft_requested` | co-estimator | 2 (or 3 if ≥$250K) |

## Agent chaining (RFI flow as the canonical example)

1. `rfi.created` event arrives.
2. TriageDispatcher runs **rfi-triage** with the RFI body + spec corpus.
3. Triage output: classification (discipline, priority, related specs, escalations).
4. If confidence ≥ 0.7 AND no escalation flags AND lane = 2: dispatcher chains to **rfi-drafter** with triage output + spec citations + prior RFI history.
5. Drafter output: draft response markdown + confidence + cited spec sections.
6. Single combined queue item submitted with both triage classification AND draft response in `proposed_action.payload`.
7. Approval Queue stores it; UI renders it with the draft visible in the detail sheet "Recommended action" + "Draft response" panels.

## Implementation plan (4 commits, single subagent)

### Commit 1: TriageDispatcher daemon
- New file `runtime/runtime/triage_dispatcher.py`
- Class `TriageDispatcher` with:
  - `async start(event_source: AsyncIterable[Event])` — main loop
  - `async dispatch(event: Event) -> AgentRun | None` — routes one event
  - Subscribes to events from a configurable source: in dev, polls the mock-data feeder log; in prod, hits Procore webhooks (out of scope for this sprint).
- Config: `TRIAGE_DISPATCHER_ENABLED=true`, `TRIAGE_EVENT_SOURCE=mock|webhook` (default `mock`), `TRIAGE_POLL_INTERVAL_SECONDS=5`.
- CLI: `quill-runtime triage start` to run the daemon.

### Commit 2: Agent chaining logic
- New file `runtime/runtime/chains.py`
- Class `Chain` with declared sequences:
  - `RFI_CHAIN = [rfi-triage, rfi-drafter]` (drafter only runs if triage confidence ≥ 0.7)
  - `SUBMITTAL_CHAIN = [submittal-triage, submittal-spec-validator]`
- `async run_chain(events: list, chain: Chain, queue_client: QueueClient) -> ChainResult`
- Outputs of each agent fed to next via templated `inputs`.
- Combined queue item submitted at end with the WHOLE chain's outputs in `proposed_action.payload`.

### Commit 3: Wire into mock-data dispatcher + extend Approval Queue UI
- `mock-data/quill_mock_data/dispatcher.py` — when posting to API, also publish a `triage_event` so the dispatcher picks it up. Or simpler: dispatcher polls API for unprocessed approvals.
- Web UI `web/components/queue/ApprovalDetailSheet.tsx` — when payload has `chain_outputs`, render BOTH the classification AND the draft response (collapsible markdown body).
- Add a "Live drafts" indicator in the queue list when an item has a chained draft.

### Commit 4: Verification + KNOWN_ISSUES
- `pytest -q` clean across runtime + api + web.
- E2E: trigger a mock RFI event, confirm queue item lands with draft pre-populated within 30 seconds.
- Update KNOWN_ISSUES with anything we discovered.

## Caveats baked in

- **No production webhook integration** — that's a separate sprint when we have a real Procore tenant. Dev/mock path only.
- **Chain confidence threshold (0.7)** is the dispatcher's gate. Below that, only the first agent runs and the queue item asks for human classification.
- **Lane 3 items don't chain to drafters** — too high-stakes to auto-draft.
- **Cost** — at peak project volume, ~50 chained dispatches/day × ~$0.05 each (Sonnet, prompt-cached) ≈ $2.50/day. Fits well in Tier 4 budget.

## Out of scope

- Real Procore webhooks (separate sprint when tenant is live)
- Vision input on field photos (Phase F.3 if we want)
- Inter-agent disagreement flagging (Phase F.4 — second-pair-of-eyes pattern)
