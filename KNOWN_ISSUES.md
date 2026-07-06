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

## Resolved

_(none yet)_
