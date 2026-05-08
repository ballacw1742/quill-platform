# Phase F.1 — Continuous Triage + Live Drafts — Verification Report

**Branch:** `feat/continuous-triage`
**Commits:** 4 (387a60e, 604b0d2, 354cd71, this one)
**Status:** All component tests pass. Live LLM E2E not run from this
subagent's environment (no Anthropic key in scope); CLI plumbing + chain
routing verified end-to-end against real mock-data dispatch.log.

## Tests

| Suite      | Before | After | Delta |
|------------|--------|-------|-------|
| runtime    | 76     | 110   | +34   |
| api        | 79     | 79    | 0     |
| mock-data  | 20     | 20    | 0     |
| web        | 39     | 45    | +6    |
| **total**  | 214    | 254   | +40   |

`tsc --noEmit` clean; `vitest run` clean.

## CLI smoke (no live LLM)

```
$ ../.venv/bin/python -m runtime.cli triage replay /tmp/triage-smoke.log
{"kind": "unknown.event", "event_id": "smoke-1", "event": "triage.dispatch.no_chain", "level": "info", "timestamp": "2026-05-08T22:21:56.420410Z"}
{
  "events_seen": 1,
  "chains_run": 0,
  "chains_succeeded": 0,
  "chains_failed": 0,
  "events_skipped": 1
}
```

Confirmed:
- `quill-runtime triage start` and `quill-runtime triage replay` both wire up.
- TRIAGE_EVENT_SOURCE / TRIAGE_POLL_INTERVAL_SECONDS / TRIAGE_DISPATCHER_ENABLED env vars honored.
- Unknown event kinds skip cleanly without invoking the LLM.

## Integration test smoke (real dispatcher → real log → real source, mocked chain)

`runtime/tests/test_triage_integration.py::test_dispatch_log_to_triage_dispatcher_end_to_end`:
- Generates a real RFI feeder event.
- Real mock-data Dispatcher writes a real dispatch.log line including the
  new `payload` and `event_id` fields.
- Real MockDataEventSource picks up the line within one poll cycle.
- TriageDispatcher routes to RFI chain (mocked) and stamps a queue submission.

`...::test_dispatcher_picks_up_event_within_5_seconds`:
- Dispatcher started + feeder fires event 200ms later.
- Pickup measured at <5s (Charles's quality bar from the spec).

## Files changed (this branch vs origin/main)

```
$ git diff --stat origin/main...HEAD
```
(see PR diff)

## E2E with live LLM — NOT RUN

This subagent did not have an Anthropic API key wired into its config and
did not boot the full api/web/bot/mock-data stack. The orchestrator
(main agent) should run the canonical happy path:

1. `make dev` (api), `cd web && npm run dev`, `make bot-dev`, `make mock-start`.
2. Source `.env` with ANTHROPIC_API_KEY.
3. `make triage-dispatcher` in a separate shell (foreground; tail logs).
4. Trigger `cd mock-data && ../.venv/bin/quill-mock cli tick --kind rfi --count 1`
   or wait for the next mock-data tick.
5. Within 30s expect:
   - dispatch.log line with `payload` + `event_id`.
   - `quill-runtime triage` log line `triage.dispatch.done` with `chain=rfi.full_triage` and `steps=2`.
   - New approval in the API at `GET /v1/approvals` whose `proposed_action.payload.chain_outputs.steps` has length 2.
   - Queue UI row for that approval shows the ✨ "Live draft" chip.
   - Tap → detail sheet shows "Triage classification" + "Draft response" panels both expanded.

If any of the above doesn't happen within 60s, check:
- `TRIAGE_DISPATCHER_ENABLED` not set to `false`.
- `mock-data/_state/dispatch.log` permissions readable by the dispatcher.
- ANTHROPIC_API_KEY present + valid in dispatcher's environment.

## Caveats (severity tagged)

See `web/KNOWN_ISSUES.md` Phase F.1 section (entries F1.1–F1.6).

Highest-severity item: **F1.5 (visible-tolerable)** — TriageDispatcher's
dedup is in-memory and capacity-bounded at 5,000. Daemon restarts cleanly
but at >5k events without restart, very-old events that get rewound
*could* retrigger. Real fix: persistent dedup table in the API
`audit_log_entries` (out of scope here).

## Architecture summary

```
mock-data feeders → mock-data Dispatcher → POST /v1/approvals
                                       ↓
                             dispatch.log (JSONL, fsynced)
                                       ↓
                       TriageDispatcher (polls every 5s)
                          ↓                       ↓
                        chains.py:run_chain   stats / outcomes
                          ↓
                  rfi-triage.run() → rfi-drafter.run()
                          ↓ confidence ≥ 0.7, no escalations, lane 2
                          ↓
              POST /v1/approvals (one combined item)
                          ↓
              proposed_action.payload.chain_outputs:
                { chain_id, steps[], skipped, errors }
                          ↓
              Web UI:
                ApprovalRow → ✨ Live draft chip
                ApprovalDetailSheet → ChainOutputsPanel:
                  • Triage classification (open by default)
                  • Draft response (markdown, rehype-sanitized)
```
