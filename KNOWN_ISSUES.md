# KNOWN_ISSUES.md

Caveats accumulated across sprints. Format:

> `<area>` — `<short>` — `<severity>` — `<sprint to address>` — `<notes>`

Severity: `(invisible)` `(visible-tolerable)` `(visible-frustrating)` `(blocking)`

---

## Sprint Gemma.1 — Local routing for Gemma 4 12B

- `runtime/test_queue_client` — 5 pre-existing tests fail in full-suite collection ordering because some sibling test leaks an httpx attr (`MockTransport`). Tests pass in isolation. — `(invisible)` — fix in next runtime cleanup sprint — Not caused by Gemma.1; reproduced on `main` before any changes.
- `runtime/eval_harness` — `eval_harness.run_parity` is single-threaded; large eval sets serialize per-sample. — `(visible-tolerable)` — Sprint Gemma.2 — add concurrency knob.
- `local_llm_client` — Token counts rely on Ollama's `prompt_eval_count` / `eval_count`, which may be inaccurate for MLX-quantized models. — `(invisible)` — Sprint Gemma.2 — confirm vs. external tokenizer.
- `model_router` — When `cost_class=local-only` fails, we surface as `LLMError` but don't capture local-specific telemetry (e.g. Ollama queue depth). — `(invisible)` — Sprint Gemma.3 — add probe.
- `Gemma 4 12B cold-start latency` — First call after model load takes ~15-20s. Subsequent calls are fast (~2-4s). — `(visible-tolerable)` — Sprint Gemma.2 — add keep-alive ping daemon.
