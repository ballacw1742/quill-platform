# agent-cloud — Known Issues

Severity legend: (invisible) internal only · (visible-tolerable) noticeable,
nothing breaks · (visible-frustrating) users hit it early · (blocking).

## A2 (memory subsystem)

1. **Live Gemini embeddings unverified — env `GEMINI_API_KEY` reported leaked.**
   During A2 verification the key present in the dev environment returned
   `403 PERMISSION_DENIED: "Your API key was reported as leaked. Please use
   another API key."` from the Gemini API. The key must be rotated and stored
   in Secret Manager (`--update-secrets GEMINI_API_KEY=...` in the deploy
   workflow) before vector memory works in prod. Until then the memory
   subsystem runs in its designed degraded mode: memories save without
   embeddings and `memory_search` uses keyword (ILIKE) fallback.
   *(visible-tolerable — memory works, recall quality is keyword-grade; rotate
   the key to upgrade to semantic search. Rows saved while degraded stay
   un-embedded; a backfill can be added later if needed.)*

2. **`CREATE EXTENSION vector` needs a privileged role on vanilla Postgres.**
   pgvector is not a "trusted" extension, so the app role can't create it on
   a plain Postgres (verified locally: `permission denied to create extension
   "vector"`; migrations catch this and degrade cleanly with a NOTICE). On
   Cloud SQL the `postgres`/`cloudsqlsuperuser` user can create it; if the
   app's DATABASE_URL role can't, run once as an admin:
   `CREATE EXTENSION IF NOT EXISTS vector;` — the next deploy's migrations
   then add the `embedding` column + HNSW index automatically (they're
   conditional on the extension existing). *(invisible once done; one-time op)*

3. **Vector dimension is fixed at table-creation time.** `EMBEDDING_DIM`
   (default 768) must match the `vector(768)` column. Changing embedding
   models to a different dimensionality requires a manual column migration +
   re-embedding. *(invisible — config discipline)*

4. **Vertex embeddings path is config-gated but unexercised** (same status as
   the Vertex Claude provider — project quota 0, SPIKE_FINDINGS.md). It fails
   with a clean named error incl. a quota hint. *(invisible)*

## A1 (carried forward)

- `/healthz` on `*.run.app` is intercepted by Google's frontend — external
  health checks must use `/health` (see README). *(visible-tolerable, ops-only)*
- Vertex Claude provider blocked on quota increase; Anthropic-direct is the
  live path. *(invisible — config cutover when quota lands)*
