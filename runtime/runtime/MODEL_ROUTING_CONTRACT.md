# Model Routing Contract (Gemma 4 / Local-vs-Remote)

**Status:** Sprint Gemma.1 — Authoritative. Read before modifying any LLM call path.

This contract defines how the runtime decides whether a given agent invocation
runs on a **local model** (Gemma 4 12B via Ollama) or a **remote model**
(Anthropic Claude). It also defines the `LLMResponse` interface contract that
both backends must satisfy so the rest of the runtime is backend-agnostic.

---

## 1. `cost_class` — the agent front-matter knob

Every agent's `system.md` front-matter MAY declare a `cost_class`:

```yaml
cost_class: local-preferred   # try local first; on failure, fall back to remote
cost_class: local-only         # local-only; on failure, raise (no remote fallback)
cost_class: remote-only        # always remote (default if omitted)
cost_class: remote-preferred   # alias for default
```

**Default when omitted: `remote-only`.** Safer per Charles's Q2 answer.

The runtime maps `cost_class` → routing decision at call time. The mapping is
the only source of truth; do NOT branch on `agent_id` anywhere.

## 2. Local backend selection

When the router picks "local", it uses the model named by env var
`LOCAL_MODEL_NAME` (default `gemma4:12b-mlx`) against the Ollama server
at `LOCAL_INFERENCE_URL` (default `http://localhost:11434`).

The agent front-matter MAY pin a specific local model via `local_model`:

```yaml
cost_class: local-preferred
local_model: gemma4:12b-mlx
```

If `local_model` is omitted, the env default is used.

## 3. `LLMResponse` interface contract

Both `AnthropicBackend` and `OllamaBackend` MUST return a `LLMResponse`
with the same dataclass shape (see `llm_client.py`). Fields the local
backend cannot populate are set to sentinel zero/false values; they MUST
be present so downstream code (`agent.py`, audit, eval harness) doesn't
branch on backend.

| Field                           | Anthropic | Ollama          |
|---------------------------------|-----------|-----------------|
| `text`                          | required  | required        |
| `model_used`                    | required  | required (`backend:gemma4:12b-mlx`) |
| `input_tokens`                  | required  | best-effort (Ollama returns `prompt_eval_count`) |
| `output_tokens`                 | required  | best-effort (`eval_count`) |
| `latency_ms`                    | required  | required        |
| `attempts`                      | required  | required        |
| `fell_back`                     | required  | required (True when local→remote fallback fired) |
| `cache_hit`                     | required  | always False    |
| `cache_creation_input_tokens`   | required  | always 0        |
| `cache_read_input_tokens`       | required  | always 0        |
| `cache_used`                    | required  | always False    |
| `backend`                       | "anthropic" | "ollama"      |

`backend` is a new field — additive, defaults to `"anthropic"` so existing
code remains compatible.

## 4. Routing algorithm

```
inputs:
  cost_class       # from agent front-matter (default remote-only)
  override_model   # from CLI --model or DEFAULT_MODEL_OVERRIDE env

if override_model is set:
  → route to backend implied by override_model name
    (names starting with "claude-" → anthropic; everything else → local)

if cost_class == "remote-only" or "remote-preferred" or omitted:
  → anthropic with spec.default_model, upgrade_model = spec.upgrade_model

if cost_class == "local-preferred":
  → ollama with local_model (front-matter > env LOCAL_MODEL_NAME)
  → on LLMError: fall back to anthropic with spec.default_model
    (fell_back=True, log "llm.call.local_fallback")

if cost_class == "local-only":
  → ollama with local_model
  → on LLMError: raise; no fallback
```

## 5. Configuration env vars (additive)

| Var                    | Default                  | Purpose                          |
|------------------------|--------------------------|----------------------------------|
| `LOCAL_INFERENCE_URL`  | `http://localhost:11434` | Ollama base URL                  |
| `LOCAL_MODEL_NAME`     | `gemma4:12b-mlx`         | Default local model              |
| `LOCAL_TIMEOUT_S`      | `120`                    | Per-call timeout (Gemma is slow on cold start) |
| `LOCAL_DISABLE`        | unset                    | If `1`/`true`, force remote regardless of `cost_class` (kill switch) |

All routing decisions log `llm.route.decision` with `{agent_id, cost_class, chosen_backend, model}` so we can audit later.

## 6. Eval harness output contract

The eval harness writes one JSON line per sample to
`runtime/_eval_runs/<agent_id>/<run_id>.jsonl` with this shape:

```json
{
  "agent_id": "rfi-triage",
  "sample_id": "RFI-DC1-A-0247",
  "backend": "ollama",
  "model": "gemma4:12b-mlx",
  "validation_ok": true,
  "validation_errors": [],
  "lane_decision": "tier-1-spotcheck",
  "latency_ms": 12341,
  "input_tokens": 1842,
  "output_tokens": 412,
  "fell_back": false,
  "raw_text_preview": "..."
}
```

A sibling summary file `summary.json` aggregates:
- count, valid_count, valid_pct
- p50/p95 latency
- total input/output tokens
- fell_back count

This is the substrate for measuring quality parity between local and remote.

## 7. What the runtime MUST NOT do

- Don't branch on `agent_id` anywhere except in agent prompts themselves.
- Don't make the local backend silently fall back to remote unless `cost_class=local-preferred`.
- Don't log API keys (Anthropic) or full payloads at INFO.
- Don't change the existing `LLMResponse` field semantics. Backend addition is additive only.

## 8. Migration list (Phase 1)

The following agents flip from `cost_class` unset (= remote-only) to `local-preferred`:

1. `contract-extractor` — text extraction; structured output; rerunnable.
2. `progress-capture` — image/text captioning; non-binding output.
3. `rfi-triage` — classification; we already have the eval harness here.

Phase 2 candidates: `dfr-synthesizer`, `submittal-triage`, `design-classifier`, `safety-aggregator`, `schedule-reader` (decided based on Phase 1 eval results).

Phase 3 (later): `progress-capture` audio mode, real-time agent loops, on-the-fly transcription.
