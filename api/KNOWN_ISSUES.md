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

## Phase G.4 — Estimate polish (May 9 2026)

1. **`(visible-tolerable)` DWG extraction requires ODA File Converter.**
   `DwgExtractor` shells out to the free Autodesk ODA File Converter to
   produce a DXF and re-extracts via `DxfExtractor`. If the binary is
   not on `PATH` (or in `/Applications/ODAFileConverter.app/...` on
   macOS), the result returns `extraction_status='failed'` with summary
   "DWG files need conversion. Install ODA File Converter (free at
   opendesign.com) or convert to DXF in any CAD tool." Soft-status
   `entities.extraction_status_detail = 'needs_conversion'` is
   surfaced for the design-classifier agent. Native `libredwg` is NOT
   in Homebrew on macOS and building from source is brittle, so we
   deliberately ship without it.

2. **`(visible-tolerable)` RVT extraction requires Autodesk APS credentials.**
   `RvtExtractor` uses the new `app.services.aps.APSClient` (Model
   Derivative API). When `APS_CLIENT_ID` and `APS_CLIENT_SECRET` are
   unset, returns `extraction_status='failed'` with summary
   "RVT extraction needs Autodesk APS credentials… Or export your RVT
   to IFC from Revit and upload the IFC instead." Soft-status
   `entities.extraction_status_detail = 'not_configured'`. The full
   APS pipeline (auth → bucket → upload → translate → poll → metadata
   → quantities) is implemented + unit-tested with httpx.MockTransport;
   it just doesn't run in dev.

3. **`(invisible)` APS uploads use single-PUT (no resumable for >100MB).**
   APS requires resumable multi-part uploads for files larger than
   ~100MB. RVTs under that cap upload fine; floor-level building models
   are usually well under. Multi-part upload is a follow-up if/when we
   see a real RVT exceed it.

4. **`(visible-tolerable)` XER export omits RSRC / TASKACTV / UDFTYPE tables.**
   `ScheduleToXer` emits ERMHDR + PROJECT + CALENDAR + PROJWBS + TASK +
   TASKPRED + EOF. Missing optional tables P6 synthesizes at import
   time; the resulting schedule round-trips with activities, durations,
   relationships, and milestone flags intact, but resource assignments
   and code-value structures are not preserved. Adequate for v0.1
   "import schedule into P6 as a starting point."

5. **`(visible-frustrating)` Agent prompt gaps surfaced by the smoke test.**
   The G.4 smoke (`api/scripts/smoke_estimate_pipeline.py`) ran both
   agents end-to-end against live Anthropic and produced sensible
   business outputs (Class 5, $1.39B/96MW DC, 1490d schedule), but
   schema validation failed on:
   - `design-classifier` invented two evidence categories
     (`civil_site_detail`, `bim_model_quality`) not in the enum, and
     wrote a summary longer than the schema's max length.
   - `estimator-scheduler` emitted citation objects with `purpose` (not
     in schema) instead of the schema-required `kind` field.
   These are agent-prompt issues — the runtime, validation, and Quill
   pipeline all worked. Tracked for the next agent-prompt revision in
   `agentic-pmo-prompts/`.

6. **`(invisible)` Smoke test bypasses the API + Approval Queue layer.**
   For cost/control reasons the smoke runs the runtime `Agent.run()`
   in-process and writes nothing to the queue. End-to-end including
   the approval-queue dispatch + execute-on-approve loop is exercised
   by the pytest suite (mocked LLM); a "true" full-stack smoke (boot
   API + post real upload + wait for approval webhook) is deferred.

7. **`(invisible)` Runtime LLM client patches (uncovered by smoke).**
   - Default `max_tokens` raised from 2,000 → 16,000. The classifier was
     hitting the 2k cap on Sonnet 4.6 and producing truncated JSON.
   - Newer Anthropic models (`claude-opus-4*`) reject the `temperature`
     parameter as deprecated. The client now omits it for that family.
   - `validator.py` builds a `referencing.Registry` from the prompts
     repo's `schemas/` dir on first use so `https://agentic-pmo.local/...`
     `$ref`s resolve locally.
