# LOVABLE_PORT_CONTRACT.md — Lovable UI → Prod Next.js port

Authored by Axe (orchestrator) before any screen work. **Every sub-agent on this
port reads this file first and does not invent conventions not in it.** (LESSONS #1, #4, #10.)

## Goal (Option 1, chosen by Charles 2026-07-18)

Carry the **Lovable redesign's visual layer** (layout, composition, JSX/Tailwind)
onto prod's existing **Next.js 14 App Router** frontend, wired to prod's **real
`lib/api.ts`** data layer. We are NOT migrating frameworks. Prod's structure,
routing, auth, websocket, and API hooks stay. We change what screens *look like*.

- Source (design truth): `/Users/charlesmitchell/.openclaw/workspace/quill-platform-builder`
  (TanStack Start + React 19 + Tailwind v4, mock in-memory stores).
- Target (prod): `/Users/charlesmitchell/.openclaw/workspace/quill-platform/web`
  (Next 14 + React 18 + Tailwind v3), branch **`feat-lovable-ui-port`**.
- Safety tag: `pre-lovable-ui-port-59c7778`.

## The three bridges (and the rule for each)

### 1. Framework/routing: TanStack Router → Next App Router
- Builder route files live in `src/routes/*.tsx` using `createFileRoute("/path")`
  + `<Link to="/x" params={...}>` + `useRouterState`/`useParams` from
  `@tanstack/react-router`.
- Prod route = `app/<segment>/page.tsx` (`"use client"`), navigation via
  `next/link` `<Link href="/x">` + `useRouter().push()` + `useParams()` /
  `usePathname()` from `next/navigation`.
- **Rule:** Recreate each Builder route as the matching prod `page.tsx`. Rewrite
  ONLY the routing wrapper + navigation calls. The *visual component bodies*
  (markup + Tailwind classes) carry over as close to 1:1 as possible.
- Dynamic-segment name mapping (Builder → prod), do NOT rename prod segments:
  - `projects.$id`         → `app/projects/[id]/page.tsx`
  - `journey.$projectId.$phase` / `journey.$projectId.index` → NEW prod routes
    `app/journey/[projectId]/[phase]/page.tsx` and `app/journey/[projectId]/page.tsx`
  - `sites.$id`            → `app/sites/[id]/page.tsx`
  - `sites.new`           → `app/sites/new/page.tsx`
  - `estimates.$id`        → `app/estimates/[upload_id]/page.tsx`  ⚠ prod uses `[upload_id]`
  - `contracts.$id`        → `app/contracts/[upload_id]/page.tsx`  ⚠ prod uses `[upload_id]`
  - `operations.$id`       → `app/operations/[id]/page.tsx`
  - `customers.$id`        → `app/customers/[id]/page.tsx`
  - `supply-chain.$id`     → `app/supply-chain/equipment/[id]/page.tsx`
  - `approvals.$id`        → `app/approvals/[id]/page.tsx`
  - `compliance.checklists.$id` → `app/compliance/checklists/[id]/page.tsx`
  - `pipeline.deals.$id`   → `app/pipeline/deals/[id]/page.tsx`
  - `documents.$id`        → `app/documents/[id]/page.tsx`
  - `queue` → `app/queue`, `requests` → `app/requests`, `metrics` → prod has NO
    `/metrics`; the Builder home links to `/metrics`. Map `/metrics` → prod
    `/today` OR add a thin `app/metrics/page.tsx`. **Decision: add `app/metrics`
    only if a Builder metrics screen exists; else point home's Metrics tile at
    `/today`.** (Builder has `routes/metrics.tsx` → port it to `app/metrics/page.tsx`.)

### 2. Data: Builder mock stores → prod `lib/api.ts` hooks  ⚠ ENVELOPE DIFFERENCE
Builder hooks (`src/lib/quill/use-*.ts`) wrap in-memory `*-store.ts` arrays.
Prod hooks (`web/lib/api.ts`) call the real API. **Hook names match**, but
**return envelopes differ.** This is the #1 bug source (LESSONS #1). Adapt at the
screen, do not change prod api.ts return shapes.

| Concept | Builder hook returns | Prod hook returns | Adapter in ported screen |
|---|---|---|---|
| Projects list | `useProjects()` → `QuillProject[]` (bare array) | `useProjects()` → `ProjectListResponse \| undefined` = `{items,total,limit,offset}` | `const { data } = useProjects(); const projects = data?.items ?? [];` |
| Project | `useProject(id)` → `QuillProject` | `useProject(id)` → `QuillProject \| undefined` | null-guard |
| Approvals | `useApprovals()` → `ApprovalItem[]` | `useApprovals()` → `ApprovalItem[]` (bare array) | matches — no adapter |
| Requests | `useProjectRequests()` → `{items}` | `useProjectRequests()` → `{items,...}` (verify shape) | `data?.items ?? []` |
| Deliverables (per project) | `useDeliverables(projectId)` → `ProjectDeliverable[]` | `useDeliverables(...)` → verify (may be `{items}` or filtered) | verify per call; default `data?.items ?? data ?? []` |
| Milestones/Log/Links | `useMilestones/useLog/useProject*Links` | prod `useProjectMilestones/useProjectLog/useProject*Links` | ⚠ NAME DIFF: Builder `useMilestones` → prod `useProjectMilestones`; Builder `useLog` → prod `useProjectLog` |

- **Import rule:** ported prod screens import hooks from `@/lib/api` (prod), NEVER
  from `lib/quill/use-*` or `lib/quill/*-store`. The Builder store/use-*/fixtures
  files are DESIGN REFERENCE ONLY and are NOT copied into prod.
- If a Builder screen needs data prod's hook doesn't expose, STOP and surface it
  to the orchestrator — do not invent a field or a new endpoint (LESSONS #1).

### 3. Design tokens: already shared — do NOT re-import
- Builder `src/styles.css` is explicitly "ported from prod `app/globals.css` +
  `tailwind.config.ts`." Prod ALREADY ships every token used: `bg-bg`,
  `text-label-primary/secondary/tertiary`, `text-large-title/title-*/headline/
  body/subhead/footnote/caption-*`, `text-accent`, `.glass`, `.glass-strong`,
  `pt-safe`/`pb-safe`, radii, shadows.
- **Rule:** Do NOT copy Builder's styles.css or add Tailwind v4 `@theme` blocks
  into prod. Reuse prod's existing utility classes verbatim. If a Builder class
  has no prod equivalent, add it to prod `tailwind.config.ts`/`globals.css` in a
  single reviewed commit — never scatter inline hex.
- One known font delta: Builder loads Inter via Google Fonts; prod deliberately
  uses the Apple system stack (no web font). **Keep prod's system stack.** Do not
  add the Inter `<link>` (prod's `--font-sans` already lists Inter first, then
  falls back to the system stack — visually equivalent, no network font).

## Known token equivalences (do NOT substitute — these exist in prod)
- `shadow-card` EXISTS in prod (tailwind boxShadow.card). Use it; do not swap to `shadow-sm`.
- `bg-chrome-solid` does NOT exist → use `bg-bg-elevated border border-hairline`.
- `text-info/warning/success/danger`, `bg-accent-tint`, `ease-ios`, `duration-tap`,
  `ios-list-group/ios-list-row/ios-list-row-last`, `pt-safe/pb-safe/pb-home`,
  `text-large-title..caption-2`, `glass/glass-strong`, `border-hairline`,
  `no-tap-highlight`, `bg-chrome` ALL exist in prod. Reuse verbatim.

## Strip-list (never port these into prod)
- Lovable editor chrome: the `Chat / mic / ⋯ / Publish` bottom bar (Lovable IDE).
- `src/lib/lovable-error-reporting.ts`, `src/lib/error-capture.ts`,
  `src/lib/error-page.ts` — Lovable telemetry shims. Prod has `ErrorBoundary.tsx`.
- All `src/lib/quill/*-store.ts`, `*-schemas.ts`, `fixtures.ts`, `use-*.ts`,
  `requests-catalog.ts` mock data — reference only, prod uses `lib/api.ts` +
  `lib/schemas.ts`.
- TanStack `router.tsx`, `__root.tsx` shell scaffolding — prod has
  `app/layout.tsx` + `app/providers.tsx`.
- `@tanstack/*` imports. Replace with `next/*` equivalents.

## Component + shell mapping
- Builder `components/quill/MobileShell.tsx` (shell/TopBar/PagePlaceholder) →
  prod already has `components/layout/MobileShell.tsx`. **Reuse prod's shell.**
  If the Builder redesign changed the shell/nav visually, port those visual
  deltas INTO prod's shell — do not replace prod's shell wholesale (it carries
  auth gating + websocket + floating home button prod needs).
- Builder `components/quill/<module>/*` visual components → port into prod
  `components/<module>/` preserving markup/classes; wire props to prod hooks.
- Builder `components/ui/*` (shadcn/radix) → prod already has `components/ui/*`.
  Reuse prod's. Only add a missing primitive if a screen truly needs it.

## The headline visual change: HOME = Journey Map
Biggest redesign: prod home is an iOS module-tile grid; Builder home
(`routes/index.tsx`) is a **project "journey map"** — each active project shown as
an expandable accordion of its 5-phase lifecycle (Site → Estimate → Contract →
Project → Operate), plus a 2-col action-tile row (Requests / Approvals / Metrics /
Pipeline). Logic lives in `src/lib/quill/journey.ts` (pure presentational
derivation, "no schema changes"). **Port `journey.ts` into prod as
`web/lib/journey.ts`** (it consumes `QuillProject` which prod already has — verify
field parity, adapt any name diffs), then rebuild the home accordion in
`app/page.tsx` wired to prod `useProjects().data?.items`.

## Build order (SEQUENTIAL — LESSONS #10; parallel only where truly independent)
1. **Foundation** (orchestrator, no sub-agent): branch + this contract + token
   parity check (DONE). Add `web/lib/journey.ts` + any missing tailwind utility.
2. **Vertical slice first:** shell visual deltas + HOME journey-map + one project
   detail. Prove the pattern end-to-end before scaling. Orchestrator runs the
   smoke.
3. **Module screens** ported in small batches, each batch = independent screens
   (no shared file writes). Each screen: recreate page.tsx, port visual body,
   wire prod hook w/ correct envelope adapter, `data?.items ?? []`.
4. **Verify:** `npm run build` + `npm run test` (vitest) green; typecheck clean;
   screenshot-compare each ported screen vs the Lovable render for parity;
   orchestrator runs end-to-end happy path (login → home → open project →
   approvals) himself (LESSONS #3).
5. **Preview branch → Charles review → deploy only on his sign-off** (SOUL hard
   rule: never touch prod without approval).

## Hard rules for every sub-agent (verbatim in each brief)
- Work ONLY on branch `feat-lovable-ui-port`. Do not merge to main. Do not push.
- Import data hooks from `@/lib/api` only. Never from Builder `lib/quill/*`.
- Reuse prod design tokens/utilities; no inline hex, no Builder styles.css.
- Match prod list-envelope: `const items = data?.items ?? []`. Never assume bare array unless the table above says so.
- No emojis in any UI text or asset (MEMORY.md hard rule).
- Do not declare a step "manual/impossible" without the 4-part Truly-Manual gate (LESSONS #9).
- Preserve prod behavior: auth gating, websocket, floating home button, approval flows stay wired.
- Report back with: files changed, which prod hooks wired, any envelope/field mismatches found, and `npm run build`+`test` output. Surface caveats with user-visible severity tags.
