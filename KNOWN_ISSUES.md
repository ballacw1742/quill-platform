# KNOWN_ISSUES.md

Tracked caveats deferred from sprints. Each entry has an owner sprint or "post-handover".

## Open

| # | Issue | Severity (user-visible) | Found | Fix target |
|---|-------|------------------------|-------|------------|
| 1 | `dev_chat` routes 500: `Settings` has no `WORKER_URL` attribute (4 failing tests in `test_dev_chat.py`). Pre-existing from Sprint DC.2. | invisible (dev-only chat surface) | Sprint 5.4 completion pass (2026-07-06) | post-handover hardening |
| 2 | `test_estimates.py::test_export_xer` and `test_notifications.py::test_telegram_backend_missing_token` are test-order dependent — pass in isolation, fail in full-suite order. | invisible (test hygiene only) | Sprint 5.4 completion pass (2026-07-06) | post-handover hardening |
| 3 | Two dev sqlite DBs exist (repo root `quill_dev.db` = canonical per Makefile, plus `api/quill_dev.db`); which is used depends on CWD at boot. Footgun for local dev. | invisible | Sprint 5.4 completion pass (2026-07-06) | post-handover hardening |
| 4 | `GET /v1/compliance/checklists` ignores `campus_id` query param (rows carry `campus_id`, filter not implemented). | visible-but-tolerable | Sprint 5.4 | post-handover |
| 5 | Deploy Campus modal doesn't expose optional `address` / `mw_capacity` / `pue_target` overrides; template defaults + project address used. | visible-but-tolerable | Sprint 5.4 | post-handover (add if requested) |
| 6 | Running pytest with `.env` sourced produces 9 false failures (webauthn RP-ID hash, SLA, worker auth) — env leakage into test expectations. Correct baseline is `make test` (no `.env`). | invisible (test hygiene) | Final regression pass (2026-07-06) | post-handover hardening |
| 7 | `datasite-agents` Cloud Run service carries a plaintext `BRAVE_API_KEY` env var — should move to Secret Manager like the other keys. | invisible (infra hygiene) | Key-rotation audit (2026-07-06) | post-handover |
| 9 | `POST /v1/auth/register` is publicly open on the deployed API while `DEV_AUTH_FALLBACK=true` — anyone can self-register an observer account. Acceptable for demo phase; disable the fallback (or gate registration) before real customers. | visible-but-tolerable (security) | Login-fix pass (2026-07-06) | pre-launch |
| 10 | Prod DB has two `owner`-role users (`white.1284@gmail.com`, `charles@monarktechnology.com`) plus a stray `newtest99@example.com` test user. Harmless, but worth pruning. | invisible (data hygiene) | Login-fix pass (2026-07-06) | post-handover |

## Resolved

| # | Issue | Resolution |
|---|-------|-----------|
| 8 | Old `quill-adk-agents` images contained revoked Gemini key + `openclaw-adk-key.json` SA key baked into layers. | 2026-07-06: leaked SA key deleted from IAM (0 user-managed keys remain), both dirty Cloud Run revisions (00001/00002) deleted, both dirty image digests deleted from gcr.io + Artifact Registry, local `gcp-adk/openclaw-adk-key.json` removed. Nothing referenced the key (verified by repo/config grep); no replacement key minted. |
| — | Deployed `quill-agents` had no `DATABASE_URL` (CI's `--set-env-vars` clobbered env on every deploy) → API fell back to empty ephemeral SQLite → all logins 500'd. | 2026-07-06: secrets attached to the service (`DATABASE_URL`, `DATABASE_URL_SYNC`, `SECRET_KEY`, `AGENT_SHARED_SECRET`, `ACTION_ASSERTION_SECRET` via Secret Manager), WebAuthn/CORS env set for the deployed domain, CI workflow switched to `--update-env-vars` (merge, not clobber), `bootstrap-owner` `MultipleResultsFound` bug fixed. Login verified end-to-end through quill-web proxy. |
