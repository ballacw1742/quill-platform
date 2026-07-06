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
| 8 | Older `quill-adk-agents` image revisions in the registry contain the now-revoked Gemini key AND `openclaw-adk-key.json` (service-account key) baked into layers via `COPY . .`. Fixed going forward (.dockerignore + Secret Manager), but the SA key should be rotated and old image revisions deleted. | invisible (security follow-up) | Key-rotation audit (2026-07-06) | needs Charles decision |

## Resolved

_(none yet)_
