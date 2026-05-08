# API Known Issues

A running list of caveats / things deferred to later sprints. Each entry
has a **user-visible severity** tag (per CONTRIBUTING_AGENTS.md \u00a76):

- `(invisible)` \u2014 internal only; the user never notices
- `(visible-tolerable)` \u2014 user might notice but it doesn\u2019t break anything
- `(visible-frustrating)` \u2014 user will hit this in their first hour and be annoyed
- `(blocking)` \u2014 prevents the canonical happy path

## Phase D.1 \u2014 Documents service (May 8 2026)

1. **`(invisible)` tsvector full-text search is Postgres-only.**
   In dev (SQLite) we transparently fall back to case-insensitive `LIKE`
   across `title | summary | body_markdown`. Search still works; results
   are unranked and snippets are heuristic. Switch dev to Postgres if
   you want to test the production search path locally.

2. **`(visible-tolerable)` PDF / DOCX export is stubbed.**
   `GET /v1/documents/{id}/export?format=pdf` and `?format=docx` return
   the markdown body with a stub header (and filename suffixed with
   `.pdf.md` / `.docx.md`) so the UI export sheet (D.2) can wire its
   actions. A real PDF/DOCX renderer (likely `markdown-pdf` or
   `pandoc`) is deferred to Phase D.3.

3. **`(visible-tolerable)` Drive export is best-effort and async.**
   Document creation is never blocked on Drive. We schedule a `gog drive
   upload` subprocess in the background and stamp `drive_url` back when
   it returns. Failure modes (no `gog` CLI, network down, auth missing)
   log a warning and leave `drive_url=null`; `GET /v1/documents/{id}/drive_link`
   returns `{ "url": null, "pending": true }`. Drive export is OFF by
   default in dev (`DOCUMENTS_DRIVE_ENABLED=false`) and stays off in
   tests.

4. **`(invisible)` MinIO is a local filesystem mirror.**
   `body_markdown` is also written to
   `${DOCUMENTS_BLOB_PATH}/documents/<YYYY>/<MM>/<artifact_id>.md`. The
   key shape is S3-compatible; swapping in real MinIO is a backend
   change with no API impact. The Postgres row is the system of record;
   blob write failures log + continue.

5. **`(invisible)` Document schemas live in the flat `app/schemas.py`.**
   The Phase D.1 brief asked for `api/app/schemas/documents.py`. Turning
   `app.schemas` into a package risks breaking ~40 existing
   `from app.schemas import \u2026` callers. Document classes are clearly
   delineated under a header and re-exported from the same flat module.
   Functionally equivalent; rename if/when we ever shard schemas.

6. **`(invisible)` `reindex` on Postgres is essentially `ANALYZE`.**
   The tsvector column is `STORED GENERATED`, so no rebuild is needed
   under normal conditions. The endpoint is kept for parity with the
   spec and as a future hook if we ever migrate to a non-generated
   column.

7. **`(visible-tolerable)` No per-document permissions yet.**
   Any authenticated Quill user (any role) can see all documents. The
   spec explicitly defers per-document ACLs to a later phase; consistent
   with how approvals + audit currently work.
