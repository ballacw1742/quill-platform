# Vendored prompts snapshot — quill-dispatch-worker

These files are a **build-time snapshot** of the agent prompts + output
schemas that the four dispatch loops need. They are baked into the
`quill-dispatch-worker` Docker image (`PROMPTS_REPO_PATH=/app/prompts`) so the Cloud
Run worker has **no network or filesystem dependency** on the prompts repo
at runtime.

- **Source repo:** `agentic-pmo-prompts`
  (local checkout: `/Users/charlesmitchell/.openclaw/workspace/agentic-pmo-prompts`)
- **Snapshot commit:** `85390b7b5507c2d2749a183c2d2319b5d27f9922`
  ("contract-extractor: add system.md (runtime loader reads system.md, not agent.md)")
- **Snapshot date:** 2026-07-06

## What's vendored

- `agents/<agent-id>/system.md` for the four dispatcher agents:
  - `contract-extractor` (contract dispatcher)
  - `contract-reviewer` (contract-review dispatcher)
  - `design-classifier` (classification dispatcher)
  - `estimator-scheduler` (estimator dispatcher)
- `schemas/*.schema.json` — the **entire** schemas directory (172K).
  The runtime validator resolves `$ref`s against the schemas root
  (e.g. `pm_artifact_base.schema.json`), so copying all of them avoids
  missing-transitive-ref failures for the cost of a few KB.

## Updating

When prompts change in `agentic-pmo-prompts`:

1. `cd agentic-pmo-prompts && git pull && git rev-parse HEAD`
2. Re-copy the four `agents/*/system.md` files and `schemas/*.json` here.
3. Update the snapshot commit + date above.
4. Commit; CI rebuilds and redeploys `quill-dispatch-worker` on push to `main`
   (path filter includes `dispatch-worker/**`).
