# Documents Workspace Spec — Quill v3 Phase D

**Goal:** Add a fifth tab — **Documents** — where every artifact produced by Quill agents lives. PMs can browse, search, open, share, download, and (eventually) edit them.

## Why this exists

PM agents (Phase C) produce status updates, SOPs, RACI matrices, comms drafts, knowledge entries, etc. Right now, agent outputs live as queue items + (sometimes) Drive uploads. There's no single place to see "what has Quill produced for this project?" or to retrieve an artifact later.

The Documents tab fixes that. It's a Files-style browser inside the app, backed by a small Documents service.

## Architecture

```
Agent produces artifact
        │
        ▼
Approval queue item with artifact_type
        │
        ▼ (on approve, Lane 1 auto, or Lane 2/3 sign-off)
Documents service writes:
  - Postgres row (api/app/models.py: Document)
  - Markdown body to MinIO blob storage
  - tsvector full-text index
  - Drive export (best-effort, async)
        │
        ▼
GET /v1/documents       → list (filterable, paginated)
GET /v1/documents/{id}  → full doc
GET /v1/documents/search?q=… → fts
GET /v1/documents/{id}/export?format=md|pdf|docx → file download
```

## API surface

| Method | Path | Returns | Auth |
|---|---|---|---|
| `GET` | `/v1/documents` | `{items: [...], total, limit, offset}` | User JWT |
| `GET` | `/v1/documents/{id}` | full doc with markdown body | User JWT |
| `GET` | `/v1/documents/search?q=text` | FTS results, scored | User JWT |
| `GET` | `/v1/documents/{id}/export?format=md` | text/markdown response | User JWT |
| `GET` | `/v1/documents/{id}/drive_link` | `{ url }` if a Drive copy exists | User JWT |
| `POST` | `/v1/admin/documents/reindex` | rebuild FTS index | X-Admin |

### Document schema

```json
{
  "id": "uuid",
  "artifact_id": "uuid (from agent output)",
  "artifact_type": "status_update | coordinator_artifact | pm_analysis | comms_draft | knowledge_entry",
  "title": "≤120 chars",
  "summary": "≤280 chars",
  "body_markdown": "full content",
  "agent_id": "rfi-triage / status-update-author / etc.",
  "agent_display_name": "Status Update Author",
  "created_at": "ISO ts",
  "approved_at": "ISO ts or null (Lane 1 auto-approved)",
  "approved_by": "user_id or 'auto'",
  "approval_id": "the approval queue item that produced this",
  "tags": ["string"],
  "drive_url": "https://docs.google.com/document/… or null",
  "minio_path": "internal blob storage key",
  "search_vector": "internal Postgres tsvector"
}
```

## DB schema

New table `documents`. Migration `0005_documents.py`:

```sql
CREATE TABLE documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  artifact_id UUID UNIQUE NOT NULL,
  artifact_type TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  body_markdown TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  agent_display_name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  approved_at TIMESTAMPTZ,
  approved_by TEXT,
  approval_id UUID REFERENCES approval_items(id),
  tags TEXT[] DEFAULT '{}',
  drive_url TEXT,
  minio_path TEXT,
  search_vector tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(title,'')), 'A') ||
    setweight(to_tsvector('english', coalesce(summary,'')), 'B') ||
    setweight(to_tsvector('english', coalesce(body_markdown,'')), 'C')
  ) STORED
);

CREATE INDEX documents_search_vector_idx ON documents USING GIN (search_vector);
CREATE INDEX documents_artifact_type_idx ON documents (artifact_type, created_at DESC);
CREATE INDEX documents_agent_id_idx ON documents (agent_id, created_at DESC);
```

(SQLite has no `tsvector`; we'll fall back to LIKE-based search in dev mode.)

## Execute hook

When an approval is approved (Lane 2/3) or auto-handled (Lane 1) and the
proposed_action is "publish_artifact", the execution dispatcher creates a
Document row from the approval's payload. Implementation goes in
`api/app/services/approvals.py::execute_approval` — extend the existing
Sprint 1 stub. The dispatcher:

1. Reads `payload.artifact` from the approval.
2. Inserts a Document row.
3. Writes the markdown body to MinIO at `documents/<YYYY>/<MM>/<artifact_id>.md`.
4. Records an audit event: `document.published`.
5. Async: uploads to Drive at `/Quill/Documents/<YYYY>/<MM>/<title>.gdoc`, stores `drive_url` once back.
6. Returns success.

## UI — `/documents` tab

Per MOBILE_UX_SPEC.md aesthetics. iOS Files-style.

### Top bar
- Title: "Documents"
- Right: search icon + filter icon

### Section header (segmented or sticky):
- "All" (default)
- "Status updates"
- "Process docs"
- "Analyses"
- "Comms drafts"
- "Knowledge"

### Document row (List Row primitive, single-line dense):
- Icon by artifact_type (color-coded; status_update → `Newspaper`, sop → `BookOpen`, comms → `Mail`, raci → `Grid3x3`, knowledge → `Lightbulb`, analysis → `BarChart3`)
- Title (text-headline)
- Subtitle: agent display name + relative date ("Status Update Author · 2 days ago")
- Right chip: artifact type tag

### Document detail screen `/documents/[id]`
- Top bar with back chevron
- Hero: title, agent badge, created/approved metadata
- Body: rendered markdown (use `react-markdown` + a sanitizer)
- Bottom action bar:
  - "Open in Drive" (opens drive_url if available)
  - "Export" (opens a sheet: Markdown / PDF / Word)
  - "Share" (system share sheet on iOS — `navigator.share`)

### Empty state
- "No documents yet."
- "When Quill helpers produce status updates, SOPs, or other artifacts, they'll show up here."

## Search UX
- Tap search icon → search bar slides in
- Inline results: list of matching documents with the agent badge + relevant snippet
- Server-side FTS in production (Postgres tsvector); client-side filter in dev (SQLite)

## Tab bar update

Add Documents as the 4th tab; Audit/Activity moves under Profile (consistent with the Phase A direction Charles already approved).

| Position | Label | Icon |
|---|---|---|
| 1 | Queue | Inbox |
| 2 | Today | Sparkles |
| 3 | Documents | FileText |
| 4 | Profile | User |

Activity (formerly Audit) accessible at `/profile/activity`.

## Bot integration (touches Phase B)

Once Documents exists, the bot's `search_documents(query)` tool from Phase B
becomes real (was a stub). Implementation just hits `GET /v1/documents/search`.

## Out of scope this phase

- In-app rich-text editing (Markdown view-only this phase)
- Versioning UI (the data model supports parent_id pointers but we don't expose them)
- Cross-document links/citations renderer
- Per-document permissions (every authenticated Quill user sees all docs for now)
