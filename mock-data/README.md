# quill-mock-data

Synthetic data sources for **QPB1** — Quill Pilot Build 1, a fictional
$10B / 1.7 GW / 4-building hyperscale data center campus, ground-up
construction starting 2026-06-23.

This package gives Quill something to chew on continuously: realistic RFIs,
submittals, daily field reports, vendor procurement updates, and hyperscaler-
side inbound files — all flowing into the live Approval Queue API. Without
volume, you can't see prompt drift, queue UX, or daily-brief usefulness.

## What's in here

```
mock-data/
├── pyproject.toml
├── README.md
├── example_seed_data.md           ← sample of what bootstrap produces
├── calendar.json                   ← Charles's calendar, 30 days
├── cli.py                          ← `quill-mock` (also at quill_mock_data.cli)
├── quill_mock_data/
│   ├── project.py                  ← QPB1 metadata (buildings, reps, dates)
│   ├── seed.py                     ← spec corpus, subs, POs, IMS XER
│   ├── dispatcher.py               ← feeder events → Approval Queue API
│   ├── scheduler.py                ← APScheduler harness
│   ├── feeders/
│   │   ├── rfi.py
│   │   ├── submittal.py
│   │   ├── dfr.py
│   │   ├── procurement.py
│   │   └── hyperscaler.py
│   └── templates/                  ← Jinja2 (RFI body, DFR narrative, vendor email)
└── tests/
```

## Quick start

```bash
# from repo root
make install           # if you haven't already
pip install -e mock-data

# bootstrap the QPB1 seed (idempotent; writes to mock-data/_state/)
quill-mock bootstrap

# run feeders + dispatcher (foreground)
quill-mock start --fast        # demo mode: events every 15-120s
quill-mock start               # realistic mode: events every 45-180min

# in another shell
quill-mock status
quill-mock tick --feeder rfi --count 3 --dry-run
quill-mock stop
```

Or the Make targets:

```bash
make mock-bootstrap
make mock-start         # backgrounded
make mock-status
make mock-stop
make daily-brief-now    # fire the Daily Brief pipeline immediately
```

## Knobs

Set in env (or `.env` at repo root):

| Var | Default | Notes |
| --- | --- | --- |
| `QUILL_API_URL` | `http://localhost:8000` | API the dispatcher posts to |
| `AGENT_SHARED_SECRET` | `dev-agent-secret-change-me` | Service-account header |
| `MOCK_DRY_RUN` | `0` | `1` to skip the API POST |
| `MOCK_RFI_PER_HOUR` | `1.0` | ~10 RFIs / business day |
| `MOCK_SUBMITTAL_PER_HOUR` | `0.5` | ~5 submittals / business day |
| `MOCK_PROCUREMENT_PER_HOUR` | `1.0` | continuous |
| `MOCK_HYPERSCALER_PER_HOUR` | `0.2` | sporadic |

## How dispatch works

```
   feeders (APScheduler)
       │
       ▼
   FeederEvent { kind, payload }
       │
       ▼
   Dispatcher.build_payload()  ← maps to ApprovalCreate
       │
       ▼
   POST /v1/approvals (X-Agent-Secret)
       │
       ▼
   API places item in queue, lane-routes, audits.
```

Dispatch is also logged JSONL to `mock-data/_state/dispatch.log`. The
**Daily Brief pipeline** (`runtime/scripts/daily_brief_pipeline.py`)
reads the last 36 h of that log to surface yesterday's DFR rollup,
critical-path procurement flags, and hyperscaler inbox count.

## Tests

```bash
cd mock-data
pytest -q
```

Covers feeder output validity (every event has the required fields),
dispatcher routing (correct agent + lane for every event kind),
project bootstrap shape (4 buildings, 12 specs, 25 subs, 30 POs, ≥500
IMS activities).

## Realism gaps (known)

- **No bid log / change-order feeder** — Sprint 4 territory.
- **Vendor emails** are short single-paragraph — real vendor mail has
  attachments + threading. Good enough for triage signal; not for NLU
  fine-tuning.
- **IMS XER** is a minimal subset. P6 import will accept it but won't
  produce a critical-path calc — the dispatcher uses `cp_activity_refs`
  on POs as a proxy for CP impact.
- **Calendar.json** is static; if you need rolling calendar coverage
  past the 30-day horizon, regenerate it (script in `mock-data/`).
