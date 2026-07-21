# Deliverables Audit — Quill Platform

**Audited:** 2026-07-20  
**Auditor:** Subagent (read-only; no files modified)  
**Scope:** 15 journey steps defined in `web/lib/journey.ts`

---

## Summary

Of the 15 journey deliverables:
- **3 are fully generated AND the link is broken** (params ignored by the target page)
- **9 are NOT generated at all** (intent not in backend registry or ADK agent map; submitting the journey step's intent falls through to `classify_intent()` which reassigns a generic intent or routes nowhere meaningful)
- **3 have a working backend generator but a broken link** (the target page ignores all query params)

No deliverable has a fully working end-to-end path (GENERATED + LINK_OK) because **no target route calls `useSearchParams`** — confirmed by exhaustive grep of `web/app/**/*.tsx` returning zero results (only `node_modules/` hits).

---

## 15-Row Verdict Table

| # | Phase | Step key | Intent | Deliverable | Target href (example) | Route exists? | Params read? | Backend generator | VERDICT |
|---|-------|----------|--------|-------------|----------------------|---------------|--------------|------------------|---------|
| 1 | site | research | `site_research` | Datasite report | `/documents?project=<id>&tag=site-research` | ✅ `/documents` exists | ❌ Neither `project` nor `tag` param is read (see §Route Analysis) | ✅ `site_assessment` via `INTENT_TO_DELIVERABLE["site_research"]` → `datasite_site_evaluator` chain | **GENERATED + LINK_BROKEN(params ignored)** |
| 2 | site | evaluate | `site_scoring` | Site scorecard | `/sites?project=<id>&section=scorecard` | ✅ `/sites` exists | ❌ `section` param not read; page shows all sites in pipeline board | ✅ `site_assessment` via `INTENT_TO_DELIVERABLE["site_scoring"]` → `datasite_site_evaluator` chain | **GENERATED + LINK_BROKEN(params ignored)** |
| 3 | site | decide | `site_status` | Go/no-go memo | `/documents?project=<id>&tag=go-no-go` | ✅ `/documents` exists | ❌ Neither `project` nor `tag` param is read | ✅ `site_assessment` via `INTENT_TO_DELIVERABLE["site_status"]` → `datasite_site_evaluator` chain | **GENERATED + LINK_BROKEN(params ignored)** |
| 4 | estimate | takeoff | `cost_takeoff` | Takeoff sheet | `/documents?project=<id>&tag=takeoff` | ✅ `/documents` exists | ❌ No params read | ❌ `cost_takeoff` not in `INTENT_TO_DELIVERABLE`, not in `INTENT_TO_ADK_AGENT`, not in `_VALID_INTENTS`; falls to `classify_intent()` which returns `"estimate"` (generic) | **NOT_GENERATED(dead intent + params ignored)** |
| 5 | estimate | estimate | `estimate_package` | Estimate v1 | `/estimates?project=<id>` | ✅ `/estimates` exists | ❌ `project` param not read; shows all estimates list | ❌ `estimate_package` not in registry/ADK map; `classify_intent()` returns `"estimate"` (generic, not this intent) | **NOT_GENERATED(dead intent + params ignored)** |
| 6 | contract | draft | `contract_draft` | Contract draft | `/contracts?project=<id>&stage=draft` | ✅ `/contracts` exists | ❌ `project` and `stage` params not read | ❌ `contract_draft` not in registry; `classify_intent()` returns `"contract"` (generic → `change_order_package` via `"contract"` intent, wrong artifact) | **NOT_GENERATED(dead intent + params ignored)** |
| 7 | contract | review | `contract_review` | Redlined contract | `/contracts?project=<id>&stage=redline` | ✅ `/contracts` exists | ❌ `project` and `stage` params not read | ❌ `contract_review` not in registry/ADK map; `classify_intent()` returns `"contract"` | **NOT_GENERATED(dead intent + params ignored)** |
| 8 | contract | execute | `contract_execute` | Executed contract | `/contracts?project=<id>&stage=executed` | ✅ `/contracts` exists | ❌ `project` and `stage` params not read | ❌ `contract_execute` not in registry/ADK map; `classify_intent()` returns `"contract"` | **NOT_GENERATED(dead intent + params ignored)** |
| 9 | project | schedule | `schedule_build` | Baseline schedule | `/projects/<id>?tab=milestones` | ✅ `/projects/[id]` exists | ❌ `tab` param not read; page always mounts with `activeTab = "overview"` | ❌ `schedule_build` not in registry/ADK map; `classify_intent()` returns `"schedule"` (generic → `schedule_package`, different intent name) | **NOT_GENERATED(dead intent + params ignored)** |
| 10 | project | rfis | `rfi_management` | RFI log | `/projects/<id>?tab=log` | ✅ `/projects/[id]` exists | ❌ `tab` param not read | ❌ `rfi_management` not in registry/ADK map; `classify_intent()` returns `"rfi"` (generic → `rfi_response`, different intent name) | **NOT_GENERATED(dead intent + params ignored)** |
| 11 | project | changes | `change_order` | Change-order package | `/projects/<id>?tab=deliverables` | ✅ `/projects/[id]` exists | ❌ `tab` param not read | ❌ `change_order` not in registry/ADK map; `classify_intent()` returns `"contract"` → routes to `change_order_package` (wrong intent name match) | **NOT_GENERATED(dead intent + params ignored)** |
| 12 | project | progress | `progress_report` | Progress summary | `/documents?project=<id>&type=status_update` | ✅ `/documents` exists | ❌ `project` and `type` params not read | ❌ `progress_report` not in registry/ADK map at all; `classify_intent()` returns `"general"` | **NOT_GENERATED(dead intent + params ignored)** |
| 13 | operate | commissioning | `commissioning` | Commissioning checklist | `/operations?project=<id>&section=commissioning` | ✅ `/operations` exists | ❌ `project` and `section` params not read; shows all campus board | ❌ `commissioning` not in registry/ADK map; `classify_intent()` returns `"general"` | **NOT_GENERATED(dead intent + params ignored)** |
| 14 | operate | owner | `owner_reporting` | Owner report | `/documents?project=<id>&type=comms_draft` | ✅ `/documents` exists | ❌ `project` and `type` params not read | ❌ `owner_reporting` not in registry/ADK map; `classify_intent()` returns `"general"` | **NOT_GENERATED(dead intent + params ignored)** |
| 15 | operate | uptime | `operations_status` | Operations rollup | `/operations?project=<id>&section=uptime` | ✅ `/operations` exists | ❌ `project` and `section` params not read | ❌ `operations_status` not in registry/ADK map; `classify_intent()` returns `"general"` | **NOT_GENERATED(dead intent + params ignored)** |

---

## Intent → Generator Table

| Journey Intent | In `_VALID_INTENTS`? | In `INTENT_TO_ADK_AGENT`? | In `INTENT_TO_DELIVERABLE`? | Generator / Deliverable Type | Notes |
|----------------|---------------------|--------------------------|----------------------------|------------------------------|-------|
| `site_research` | ✅ | ✅ → `datasite_site_researcher` | ✅ → `site_assessment` | `datasite_site_evaluator` 2-step chain | Works; produces `site_assessment` row |
| `site_scoring` | ✅ | ✅ → `datasite_site_scorer` | ✅ → `site_assessment` | `datasite_site_evaluator` 2-step chain (alias) | Works |
| `site_status` | ✅ | ✅ → `datasite_site_status` | ✅ → `site_assessment` | `datasite_site_evaluator` 2-step chain (alias) | Works |
| `cost_takeoff` | ❌ | ❌ | ❌ | **NONE** | Falls through `classify_intent()` → returns `"estimate"` (generic) |
| `estimate_package` | ❌ | ❌ | ❌ | **NONE** | Falls through → `"estimate"` → `cost_estimate` chain (wrong intent name) |
| `contract_draft` | ❌ | ❌ | ❌ | **NONE** | Falls through → `"contract"` → `change_order_package` (wrong artifact) |
| `contract_review` | ❌ | ❌ | ❌ | **NONE** | Falls through → `"contract"` → `change_order_package` (wrong artifact) |
| `contract_execute` | ❌ | ❌ | ❌ | **NONE** | Falls through → `"contract"` → `change_order_package` (wrong artifact) |
| `schedule_build` | ❌ | ❌ | ❌ | **NONE** | Falls through → `"schedule"` → `schedule_package` (intent name mismatch) |
| `rfi_management` | ❌ | ❌ | ❌ | **NONE** | Falls through → `"rfi"` → `rfi_response` (intent name mismatch) |
| `change_order` | ❌ | ❌ | ❌ | **NONE** | Falls through → `"contract"` → `change_order_package` (intent name mismatch) |
| `progress_report` | ❌ | ❌ | ❌ | **NONE** | Falls through → `"general"` → `quill_coordinator` with no deliverable |
| `commissioning` | ❌ | ❌ | ❌ | **NONE** | Falls through → `"general"` → `quill_coordinator` with no deliverable |
| `owner_reporting` | ❌ | ❌ | ❌ | **NONE** | Falls through → `"general"` → `quill_coordinator` with no deliverable |
| `operations_status` | ❌ | ❌ | ❌ | **NONE** | Falls through → `"general"` → `quill_coordinator` with no deliverable |

---

## Route Analysis (Query Param Handling)

**Key finding: NONE of the target pages call `useSearchParams`.**

Confirmed by grep: `grep -rn "useSearchParams" web/app/ --include="*.tsx"` returns **zero results** (only `node_modules/` hits).

### `/documents` (steps 1, 3, 4, 12, 14)
- **File:** `web/app/documents/page.tsx`
- **Params passed:** `?project=<id>&tag=...` or `?project=<id>&type=...`
- **What the page reads:** Uses `useDocuments({ artifact_type, limit })` — the `DocumentListParams` type in `web/lib/api.ts:810` has no `project` or `tag` field. The API backend `GET /v1/documents` (api/app/routes/documents.py:85) accepts `artifact_type`, `agent_id`, `since`, `q`, `limit`, `offset` — **no `project` or `tag` parameters**.
- **Result:** `project` and `tag`/`type` query params are **silently dropped** by both frontend and backend. User sees unfiltered global document list.

### `/sites` (step 2)
- **File:** `web/app/sites/page.tsx`
- **Params passed:** `?project=<id>&section=scorecard`
- **What the page reads:** Uses `useSites()` which calls `GET /v1/sites` with no filtering. No `project` or `section` param consumed anywhere. Page renders the full pipeline kanban board.
- **Result:** Params ignored.

### `/estimates` (step 5)
- **File:** `web/app/estimates/page.tsx`
- **Params passed:** `?project=<id>`
- **What the page reads:** Uses `useListEstimates()` with no params. No project filter available.
- **Result:** `project` param ignored; shows all estimates.

### `/contracts` (steps 6, 7, 8)
- **File:** `web/app/contracts/page.tsx`
- **Params passed:** `?project=<id>&stage=draft|redline|executed`
- **What the page reads:** Uses `useContractsList({ status, source, limit })` — no `project` param, no `stage` param. `stage` does not map to the `source` param used for "drafted" filter.
- **Result:** `project` and `stage` params ignored; shows all contracts with a static filter (All/Extracted/Reviewed/Drafted).

### `/projects/[id]` (steps 9, 10, 11)
- **File:** `web/app/projects/[id]/page.tsx`
- **Params passed:** `?tab=milestones|log|deliverables`
- **What the page reads:** Uses `useParams()` for `id` only. The `activeTab` state is initialized to `"overview"` (`React.useState<TabValue>("overview")` at line 1396). No `useSearchParams()` call anywhere in the file. The `tab` param is **completely ignored**.
- **Result:** Page always opens on "Overview" tab regardless of `?tab=` value.

### `/operations` (steps 13, 15)
- **File:** `web/app/operations/page.tsx`
- **Params passed:** `?project=<id>&section=commissioning|uptime`
- **What the page reads:** Uses `useCampuses()` with no params. No `project` or `section` param consumed.
- **Result:** Params ignored; shows all campuses.

---

## Top Fixes Needed

### Priority 1 — Dead Intents (12 of 15 broken by intent mismatch)

**Root cause:** `web/lib/journey.ts` defines 12 custom intent strings (`cost_takeoff`, `estimate_package`, `contract_draft`, `contract_review`, `contract_execute`, `schedule_build`, `rfi_management`, `change_order`, `progress_report`, `commissioning`, `owner_reporting`, `operations_status`) that exist **nowhere** in the backend's `_VALID_INTENTS`, `INTENT_TO_ADK_AGENT`, or `INTENT_TO_DELIVERABLE` dictionaries.

When the journey phase page submits a request with `intent=cost_takeoff` (for example), the backend's `_valid_intents` check fails, so `classify_intent()` runs instead, returning a generic intent (`"estimate"`, `"contract"`, `"rfi"`, `"schedule"`, or `"general"`). This means:
- The journey-specific context is lost
- The wrong deliverable type may be produced (e.g. `change_order_package` for all three contract steps)
- Four intents (`progress_report`, `commissioning`, `owner_reporting`, `operations_status`) fall to `"general"` with **no deliverable produced at all**

**Fix options (pick one per intent):**
- **Option A (preferred):** Add each journey intent to `_VALID_INTENTS`, `INTENT_TO_ADK_AGENT`, and `INTENT_TO_DELIVERABLE` in the backend. Create dedicated registry entries for `cost_takeoff`, `estimate_package`, `contract_draft`, `contract_review`, `contract_execute`, `schedule_build`, `rfi_management`, `change_order`, `progress_report`, `commissioning`, `owner_reporting`, `operations_status`.
- **Option B:** Change `web/lib/journey.ts` intent strings to match existing backend intents (e.g. `cost_takeoff` → `"estimate"`, `schedule_build` → `"schedule"`, `rfi_management` → `"rfi"`, `change_order` → `"contract"`, operating intents → `"facility_ops"`). Simpler but loses specificity.

**Evidence:**  
- `web/lib/journey.ts:129` — `intent: "cost_takeoff"`  
- `api/app/routes/requests.py:1103-1109` — `_VALID_INTENTS` set (12 journey intents absent)  
- `api/app/deliverable_registry.py` — `INTENT_TO_DELIVERABLE` (12 journey intents absent)  
- `api/app/routes/requests.py:1111-1114` — fallback to `classify_intent()` when intent not in `_VALID_INTENTS`

### Priority 2 — Query Params Ignored by All Target Pages (15 of 15 broken)

**Root cause:** All journey step `target()` functions return URLs with query params (`project`, `tag`, `section`, `stage`, `type`, `tab`) that are **never read** by the target pages. No page in `web/app/` calls `useSearchParams()`.

**Sub-issues:**

1. **`/documents` pages** — params `project` and `tag`/`type` don't exist in `DocumentListParams` (`web/lib/api.ts:810`) or the backend API (`api/app/routes/documents.py:84-96`). These need to be added to both layers.

2. **`/projects/[id]` pages** — `activeTab` is hardcoded to `"overview"` at `web/app/projects/[id]/page.tsx:1396`. The `tab` param is never read. Fix: call `useSearchParams()` and initialize `activeTab` from `?tab=` if present.

3. **`/contracts` pages** — `stage` param doesn't map to any filter. The backend has no concept of `stage=draft|redline|executed` as a list filter (it uses `status` and `source` fields). Fix: either add `stage` filtering or change journey target to use `source=drafted` for draft step.

4. **`/sites` pages** — `section=scorecard` param not consumed; scorecard is shown inside `/sites/[id]` detail page, not the list. Fix: change step 2's target to `/sites/<id>` (but requires a site ID, not project ID).

5. **`/operations` pages** — `section=commissioning|uptime` not consumed. The section concept doesn't exist in the campus board UI.

**Fix:** Add `useSearchParams()` calls to each target page and wire them to filter the displayed data, OR redesign the target URLs to use routes that already support the intended filtering (e.g. `/documents/[id]` for specific documents).

### Priority 3 — Document Backend Missing `project` and `tag` Filters

Even if the frontend is fixed to pass `project` and `tag` to `useDocuments`, the backend `GET /v1/documents` (`api/app/routes/documents.py:84`) does not accept these parameters. Adding frontend filtering alone won't work without a backend change.

**Fix:** Add `project_id` and `tags` (multi-value) query params to `GET /v1/documents`, filter in `app/services/documents.py` list method.

---

## Evidence Index

| Claim | File | Line(s) |
|-------|------|---------|
| Journey intents defined | `web/lib/journey.ts` | 91, 101, 111, 129, 139, 157, 167, 177, 195, 205, 215, 225, 243, 253, 263 |
| `_VALID_INTENTS` set (excludes 12 journey intents) | `api/app/routes/requests.py` | 1103–1109 |
| `INTENT_TO_ADK_AGENT` (excludes 12 journey intents) | `api/app/routes/requests.py` | 109–166 |
| `INTENT_TO_DELIVERABLE` (only 3 site intents + 9 others match) | `api/app/deliverable_registry.py` | 369–399 |
| Fallback to `classify_intent()` when intent not in `_VALID_INTENTS` | `api/app/routes/requests.py` | 1111–1114 |
| No `useSearchParams` in any app page | `web/app/**/*.tsx` | (grep returns 0 results) |
| `/documents` page ignores `project`/`tag` params | `web/app/documents/page.tsx` | 38–45 (`useDocuments` call) |
| `DocumentListParams` has no `project` or `tag` field | `web/lib/api.ts` | 810–827 |
| Backend documents API has no `project`/`tag` params | `api/app/routes/documents.py` | 84–96 |
| `/sites` page ignores `project`/`section` params | `web/app/sites/page.tsx` | 82–91 (`useSites()` call) |
| `/estimates` page ignores `project` param | `web/app/estimates/page.tsx` | 44 (`useListEstimates()` call) |
| `/contracts` page ignores `project`/`stage` params | `web/app/contracts/page.tsx` | 33–35 (`useContractsList` call) |
| `/projects/[id]` activeTab hardcoded "overview", no `useSearchParams` | `web/app/projects/[id]/page.tsx` | 1396 |
| `/operations` page ignores `project`/`section` params | `web/app/operations/page.tsx` | 163 (`useCampuses()` call) |
| Journey page sends `intent` from step config via FormData | `web/app/journey/[projectId]/[phase]/page.tsx` | 72–79 |
| `site_assessment` registry entry with 2-step chain | `api/app/deliverable_registry.py` | 288–340 |
| `cost_estimate` registry entry (intent `"estimate"`, not `"cost_takeoff"`) | `api/app/deliverable_registry.py` | 153–196 |
| `rfi_response` registry entry (intent `"rfi"`, not `"rfi_management"`) | `api/app/deliverable_registry.py` | 197–240 |
| `change_order_package` registry entry (intent `"contract"`, not `"change_order"`) | `api/app/deliverable_registry.py` | 258–296 |
| `schedule_package` registry entry (intent `"schedule"`, not `"schedule_build"`) | `api/app/deliverable_registry.py` | 242–257 |
