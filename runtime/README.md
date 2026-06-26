# Quill Agent Runtime

The runtime that loads agent prompts from
[`agentic-pmo-prompts`](../../agentic-pmo-prompts), calls the LLM, validates the
output against the agent's JSON Schema, computes input/output/prompt hashes,
routes the result to a Lane (1/2/3) per Doc 03 §4, and submits the approval
item to the [Approval Queue API](../api).

## Install

```bash
cd runtime
pip install -e .[dev]
```

## Configuration (env vars)

| Var                          | Default                                                          | Notes                                                  |
| ---------------------------- | ---------------------------------------------------------------- | ------------------------------------------------------ |
| `PROMPTS_REPO_PATH`          | `/Users/charlesmitchell/.openclaw/workspace/agentic-pmo-prompts` | Where `agents/<id>/system.md` lives.                   |
| `QUEUE_API_URL`              | `http://localhost:8000`                                          | Approval Queue API base URL.                           |
| `AGENT_SHARED_SECRET`        | `dev-agent-secret-change-me`                                     | Must match `AGENT_SHARED_SECRET` on the API.           |
| `ANTHROPIC_API_KEY`          | _(unset)_                                                        | Required to actually call the model.                   |
| `DEFAULT_MODEL_OVERRIDE`     | _(unset)_                                                        | Force a specific model regardless of agent front-matter.|
| `ON_PREM_INFERENCE_URL`      | _(unset)_                                                        | Placeholder for Class-A on-prem routing.                |
| `LOG_LEVEL`                  | `INFO`                                                           | structlog level.                                       |
| `RUNTIME_REQUEST_TIMEOUT_S`  | `60`                                                             | HTTP timeout for the queue client.                     |
| `LOCAL_INFERENCE_URL`        | `http://localhost:11434`                                         | Ollama base URL (Sprint Gemma.1).                      |
| `LOCAL_MODEL_NAME`           | `gemma4:12b-mlx`                                                 | Default local model when `cost_class=local-*`.         |
| `LOCAL_TIMEOUT_S`            | `120`                                                            | Per-call timeout for the local backend.                |
| `LOCAL_DISABLE`              | _(unset)_                                                        | Kill switch: `1`/`true` forces remote regardless of `cost_class`. |

## Local vs. Remote Routing (Sprint Gemma.1)

Every agent's `system.md` front-matter MAY declare a `cost_class`:

- `remote-only` (default) — always Anthropic.
- `remote-preferred` — alias for the default.
- `local-preferred` — Ollama first, fall back to Anthropic on local failure.
- `local-only` — Ollama only; raise on failure.

And MAY pin a specific local model:

```yaml
cost_class: local-preferred
local_model: gemma4:12b-mlx
```

The canonical contract is documented in `runtime/MODEL_ROUTING_CONTRACT.md`.
The `LLMResponse` object carries a new `backend` field (`anthropic` | `ollama`)
so downstream code can attribute cost without inspecting model names.

### Keep-alive daemon

Gemma's first call after model unload pays a 15-20s cold-start. Pin the model
in memory with:

```bash
quill-runtime local warmup --interval 60
```

Runs in the foreground; supervisor-friendly. One-shot variant:
`quill-runtime local ping`.

### Streaming (real-time agent loops)

For token-by-token output (real-time agent loops, voice UIs, etc.):

```python
async for chunk in client.stream(model=None, system="You are concise.", user="Hi"):
    print(chunk, end="", flush=True)
```

CLI sanity-check: `quill-runtime local stream "Hi there"`.

### Audio transcription substrate (Whisper, local)

Local-only meeting transcription via the OpenAI Whisper CLI. No audio leaves
the machine. No API key.

```bash
quill-runtime transcribe ./meeting.wav \
    --model small.en \
    --out ./meeting.transcript.json
```

Produces a normalized `TranscriptArtifact` (segments, timestamps, full text)
that any agent can consume. This is the substrate Phase 3 "record everything"
workflows run on.

### Cross-backend parity eval

Measure local-vs-remote quality on a per-agent eval set:

```bash
quill-runtime evals parity design-classifier \
  --inputs runtime/scripts/synthetic_design_packages.jsonl \
  --out-dir _eval_runs
```

Writes `_eval_runs/<agent>_<run-id>.jsonl` (one row per (sample, backend)) and
`_eval_runs/<agent>_<run-id>.summary.json` with validity %, p50/p95 latency,
token totals, and pairwise lane-decision agreement.

A `.env` file in the runtime working directory is auto-loaded.

## CLI

### Run a single agent against a single input

```bash
quill-runtime run rfi-triage \
  --input runtime/scripts/synthetic_rfis/RFI-DC1-A-0247.json
```

Useful flags:

- `--no-submit` — run end-to-end but don't POST to the queue
- `--model claude-opus-4-7` — override the agent's `default_model`
- `--workflow rfi.intake` — workflow tag for the queue item

The CLI prints the full `AgentRun` (including `approval_id` if submitted).

### Inspect / register agents

```bash
quill-runtime registry list
quill-runtime registry register coordinator daily-brief submittal-spec-validator \
                                procurement-watch rfi-triage rfi-drafter submittal-triage
```

### Run the agent's eval harness

```bash
quill-runtime evals run rfi-triage --limit 5
```

This delegates to `agentic-pmo-prompts/agents/<id>/evals/run_evals.py`.

## Python API

```python
import asyncio
from runtime import Agent

async def main():
    agent = Agent("rfi-triage")
    run = await agent.run(
        {"rfi": {"id": "RFI-001", ...}, "context": {...}},
        submit_to_queue=True,
    )
    print(run.approval_id, run.lane_decision.lane, run.validation_ok)

asyncio.run(main())
```

`AgentRun` carries:
- `input_hash`, `output_hash`, `prompt_version_hash`
- `model_used`, `latency_ms`, `tokens_used`, `fell_back`
- `validation_ok` + `validation_errors`
- `lane_decision` (lane, tier, reasons, materiality flags)
- `approval_id` (if submitted)
- `error` (if anything went sideways — never raises through `run()`)

## How it talks to the API

The runtime authenticates with the API using the `X-Agent-Secret` header
(Sprint 1 service-account auth), which is implemented in
`api/app/security.py::require_agent_secret`. The `Authorization: Bearer <secret>`
header is also sent, so the runtime keeps working unmodified once the API
upgrades to a Bearer JWT for service accounts.

The runtime maps `AgentRun` → the API's `ApprovalCreate` schema in
`runtime/queue_client.py::_adapt_create_payload`. Unknown keys are dropped,
sane defaults are filled in for `agent_version`, `priority`, `target_system`,
and `payload`.

## Trust-tier routing

See `runtime/lane_router.py`. Strictness order is
`tier-2-auto < tier-1-spotcheck < tier-0-mandatory`. Materiality flags
(`cost_impact_flag`, `schedule_impact_flag` × `on_critical_path`,
`safety_flag`, `confidence < 0.70`) push toward stricter tiers, then we map:

- `tier-2-auto` → Lane 1
- `tier-1-spotcheck` / `tier-2-charles-approves` → Lane 2
- `tier-0-mandatory` → Lane 2 (default), Lane 3 if dual-approval signals fire

## Tests

```bash
cd runtime
pytest          # 30+ tests, no live API/LLM calls
ruff check
```

## Sprint 2 demo

```bash
# Terminal 1 — boot the API
cd api && uvicorn app.main:app --reload

# Terminal 2 — register agents + replay synthetic inputs
cd runtime
quill-runtime registry register coordinator daily-brief submittal-spec-validator \
                                procurement-watch rfi-triage rfi-drafter submittal-triage
python scripts/replay_synthetic.py
curl -s http://localhost:8000/v1/admin/health | jq
```
