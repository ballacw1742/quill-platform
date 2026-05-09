# KNOWN_ISSUES.md — feat/ui-ios-redesign

## Phase F.1 — Continuous Triage + Live Drafts (May 8, 2026)

F1.1 **`(visible-tolerable)` — Live draft badge depends on chain_outputs schema staying as today's shape.**
  The badge in `ApprovalRow.tsx` and the panel in `ChainOutputsPanel.tsx`
  use a heuristic to identify the triage step (agent_id contains 'triage'
  or output has `discipline`/`category`/`priority`/`spec_section`) and the
  drafter step (agent_id contains 'drafter'/'draft' or output has
  `draft_markdown`/`draft_response`/`response_markdown`). New chain agents
  with different output shapes will fall into the generic 'Other agent
  outputs' collapsible. Fix when adding non-RFI/non-submittal chains.

F1.2 **`(visible-tolerable)` — Drafter markdown is rendered through
  rehype-sanitize default schema.** Same posture as the documents tab.
  If a drafter agent produces inline HTML or scripts they get stripped;
  if they produce raw markdown they render fine. No XSS surface, but a
  drafter that emits HTML by mistake will render as plain text. Surface
  in agent eval if it shows up.

F1.3 **`(invisible)` — Chain confidence threshold is hard-coded at 0.7
  inside `runtime/runtime/chains.py`.** RFI_CHAIN and SUBMITTAL_CHAIN both
  use `confidence_gate(0.7)`. To change the threshold today you edit the
  declaration. Promote to env / config when we have telemetry showing
  the right value.

F1.4 **`(visible-tolerable)` — TriageDispatcher is dev/mock only.**
  `--source webhook` raises NotImplementedError. Real Procore webhook
  integration is a separate sprint. Production rollout requires that
  source plus event de-dup against the API's audit log (rather than the
  in-memory set used today).

F1.5 **`(visible-tolerable)` — Same dispatch.log line is consumed twice
  if the API _also_ writes to it AND the mock-data dispatcher writes
  to it AND the TriageDispatcher's in-memory dedup set is bounded at
  5,000 entries.** In a long-running daemon (>5k events without restart)
  events older than 5k slots can theoretically retrigger if the log
  gets rewound (file truncate). Practically: not a concern at our event
  volume, but a real persistent dedup table belongs in the API layer
  before we go to production.

F1.6 **`(invisible)` — TriageDispatcher imports `runtime.chains` at
  module load.** If a future chain references an agent prompt that
  doesn't exist in the prompts repo, `Agent(agent_id)` will fail at
  *first dispatch*, not at startup. Logs surface the failure and the
  daemon keeps running. Worth adding a `--validate-chains` flag that
  loads every declared chain's agents at boot.

---

# KNOWN_ISSUES.md — feat/ui-ios-redesign

Tracked rough edges from the iOS redesign sprint. Every entry has a
user-visible severity tag per CONTRIBUTING_AGENTS.md rule 6:

- `(invisible)` — internal only, user never notices.
- `(visible-tolerable)` — user might notice but it doesn't break anything.
- `(visible-frustrating)` — user will hit this in their first hour and be annoyed.
- `(blocking)` — prevents the canonical happy path.

## Carry-over from prior sprints (not introduced by this redesign)

1. **`(invisible)` — TanStack Query v5 + Zod transform inference fights**
   `lib/api.ts` hooks now use explicit `as Type` casts in their `queryFn` /
   `mutationFn` returns where the underlying schemas use `.passthrough().transform()`.
   The actual runtime types match the UI types (the transforms backfill the
   missing fields), but TypeScript's inference loses the narrowing. The casts
   are localized and don't change contracts. Future cleanup: rebuild the
   schemas without `.transform()` so the output type is statically derivable.

2. **`(invisible)` — pre-existing strict-mode shim in `lib/mock/fixtures.ts`**
   `MOCK_AUDIT` literal omits the optional `approval_id` / `agent_id` fields
   on the genesis row; cast through `as unknown as AuditEntry[]` keeps strict
   compile happy. Same root cause as #1.

## Introduced by this redesign

3. **`(visible-tolerable)` — pull-to-refresh on the queue is rudimentary**
   Implementation watches `touchstart` + `touchend` and triggers a query
   invalidation when the user starts at scrollTop=0 and pulls down >80 px.
   It works, but there's no animated spinner indicator while the request is
   in flight (the existing TanStack background-refetch happens silently).
   Real iOS apps show a UIRefreshControl spinner that follows the finger.
   Future sprint: add a visible spinner indicator.

4. **`(visible-tolerable)` — kebab menu in approval detail uses inline overlay
   instead of a Radix dropdown**
   The "Escalate / View raw JSON / Open in new screen" menu in the approval
   detail sheet is implemented as a hand-rolled absolute-positioned panel
   inside a click-outside backdrop. It works and is keyboard-dismissible
   (the backdrop button has tabIndex=-1 plus aria-hidden), but it doesn't
   close on Escape. Real iOS Action Sheets are full-width modal lists from
   the bottom. Future sprint: replace with an iOS action-sheet primitive.

5. **`(visible-tolerable)` — swipe-approve from /queue still requires
   biometric**
   When the user swipe-commits "Approve" or "Reject" on a Lane 2 row, we
   currently route to opening the detail sheet (which auto-fires the
   biometric prompt). The swipe gesture's commit doesn't bypass the
   passkey ceremony — and per the API's contract it can't, because every
   decision must be bound to a fresh passkey assertion. The UX is therefore
   "swipe + biometric" not "swipe-and-done." This is correct behaviour, but
   may surprise users who expect Mail-style instant-commit. Considered and
   intentional; documenting for future review.

6. **`(visible-tolerable)` — Today page heuristics are derived from
   useApprovals only**
   /today's "Critical path" / "Procurement watch" / "RFIs aged > 48h" /
   "Hyperscaler inbox" sections derive from string matches on
   workflow / agent_id / escalations. There's no canonical Daily Brief
   endpoint yet, so values may flicker if agents change naming
   conventions. The "Today's calendar" section is rendered as disabled
   because there's no calendar source wired. Future sprint: add a
   /v1/daily_brief endpoint that backs Today directly.

7. **`(visible-tolerable)` — /profile/agents trust-tier change uses a
   soft-confirm passkey gate, not action-bound assertion**
   The existing `useSetTrustTier` mutation contract doesn't accept a
   passkey assertion the way `useDecide` does. The BiometricPrompt for
   trust-tier changes therefore acts as a UX confirmation (covers the
   screen, asks the user to authenticate) but the assertion isn't sent to
   the API. Same behaviour as the legacy /agents page; the API enforces
   role-based gating. Future sprint: extend the trust-tier endpoint to
   accept a bound action assertion.

8. **`(visible-tolerable)` — Telegram pairing row is informational**
   /profile's "Pair Telegram" row currently surfaces a toast pointing the
   user to the @DC_QuillBot pair flow rather than implementing the in-app
   pair ceremony. The pair flow lives in the Telegram bot, not the web UI.
   Future sprint: implement an in-app pair-code QR or similar.

9. **`(visible-tolerable)` — desktop layout still uses bottom tab bar**
   Per MOBILE_UX_SPEC §"App shell" desktop should eventually get a
   left-rail sidebar. This sprint keeps the bottom tab bar for both
   mobile and desktop to ship a consistent, finished surface. The
   container max-width keeps it readable on 1440 px+. Future sprint:
   add the desktop sidebar variant.

10. **`(visible-tolerable)` — the legacy three-column /approvals/[id]
    standalone page was removed in favour of the bottom-sheet flow**
    Deep links to /approvals/[id] now land on a minimal MobileShell page
    that auto-opens the new ApprovalDetailSheet. Closing the sheet pops
    history.back(). If a user opens a deep link with no history (e.g.
    pasted URL in a fresh tab), the close button bounces to about:blank
    on some browsers. Workaround: close → tap Queue tab.

## Verification gaps

11. **`(visible-tolerable)` — biometric approval flow not end-to-end smoke
    tested by this subagent**
    I verified the API + UI proxy + JWT auth path works (curl). I did not
    fire a real passkey ceremony from a browser because the smoke
    environment doesn't have a registered platform authenticator. The
    BiometricPrompt component reuses the same `lib/auth.challengePasskey`
    plumbing as the prior PasskeyChallengeModal, which has been
    exercised in earlier sprints. Charles should run one full
    decision in mobile Safari to confirm the new sheet ↔ prompt
    handoff feels right.

12. **`(visible-tolerable)` — UI / API contract drift detection**
    The lib/api.ts adapter (`coerceApiApprovalItem`) handles the lane-int /
    lane-string mapping plus optional fields. New fields the API ships
    that aren't in the UI ApprovalItem shape will silently drop. This is
    inherited behaviour and not introduced here, but the redesign relies
    on `summary` / `rationale` / `escalations` / `priority`. If any of
    those go missing the queue still renders (degraded subtitles,
    no flag chips) — no crash.

## Phase A — plain-English copy pass (feat/ui-plain-english)

13. **`(invisible)` — `/audit` route preserved, only the visible label moved**
    Per COPY_GUIDE we renamed the bottom-tab label from "Audit" to
    "Activity" but kept the URL `/audit` so deep links and the existing
    API path (which still uses `audit_chain`, `useAudit`, `useAuditMirrorStatus`,
    etc.) don't break. If we ever want the URL to also become `/activity`,
    plan a redirect first.

14. **`(visible-tolerable)` — onboarding overlay is browser-local, not server-side**
    The "first login" flag (`localStorage.quill.onboarded`) is per-browser
    and per-device. A user who signs in on a second device will see the
    overlay again. That matches the COPY_GUIDE spec ("stored as
    quill.onboarded=true in localStorage") but Charles may eventually want
    to track onboarding completion server-side so it's a property of the
    user, not the browser.

15. **`(invisible)` — recommended-action sentence is heuristic**
    `buildRecommendedAction` in `ApprovalDetailSheet` synthesises a
    one-liner from `proposed_action.kind` + `target_system`. The output
    reads naturally for the common cases we know about ("route", "draft",
    "escalate", "flag") and falls back to a pretty-cased
    "<Kind> in <target system>." for anything else. If new action kinds
    arrive whose names don't end in those verbs, we'll fall back to the
    pretty-case path — still readable, but a touch generic. Future work:
    accept an optional `recommended_action` string from the agent and
    prefer it when present.

16. **`(visible-tolerable)` — Why-panel payload table is a flat label/value
    list**
    Nested objects in `proposed_action.payload` are stringified to
    compact JSON in the value cell. That keeps the panel out of "raw
    JSON dump" territory while still surfacing the data, but for deeply
    nested objects the value will read like `{"foo":"bar","baz":1}`.
    Acceptable for a v3 polish pass; consider expanding into nested
    label/value rows in a later iteration.

17. **`(invisible)` — dev server webpack cache mismatch after running
    `next build`**
    Running `next build` in the same checkout where `next dev` is alive
    leaves a transient cache mismatch (`Can't resolve
    './vendor-chunks/use-sidecar'`) that surfaces as a stray 404 from
    `/today` until the dev server is restarted. The production build is
    clean and `tsc --noEmit` is clean. Only affects the live dev server
    process — restart it to recover.

## Phase D.2 — Documents tab

18. **~~`(visible-tolerable)` — filter icon in /documents top bar is a no-op~~**
    **RESOLVED in Phase E (commit 4).** The right-side `SlidersHorizontal`
    button on the Documents top bar now opens a real multi-axis filter
    sheet (artifact type, helper, date range, tags). Active-filter count
    surfaces as a badge on the icon.

19. **~~`(visible-tolerable)` — More (•••) menu on /documents/[id] is a
    placeholder~~**
    **RESOLVED in Phase E (commit 4).** Tapping the menu icon now opens
    a bottom-sheet action menu with: Copy link / Open in new tab / Print
    / View raw JSON. Each closes the sheet on tap; the JSON viewer is a
    separate full-height sheet with its own copy-to-clipboard action.

20. **`(visible-tolerable)` — PDF / Word export rely on the API-side
    converter**
    `useDocumentExport(id, format)` simply streams whatever the
    `/v1/documents/{id}/export?format=…` endpoint returns. In MOCK mode
    we synthesize a tiny placeholder file so the download flow is
    exercised end-to-end. Real .pdf / .docx output quality is owned by
    the API service (Phase D.1) and is out of scope here.

21. **`(visible-tolerable)` — Drive link "uploading…" disabled state can
    persist if the API never returns a URL**
    `useDocumentDriveLink` polls every 30s while `url` is null; in the
    mock it stays null for documents that ship without a `drive_url`.
    The button copy ("Drive link still uploading…") is honest about
    that, but a doc that genuinely has no Drive copy will read the same
    way as one whose upload is mid-flight. Future: distinguish via a
    `status: "skipped" | "pending" | "ready"` enum from the API.

22. **`(visible-tolerable)` — Activity (audit) tab no longer in the
    bottom bar**
    Per DOCUMENTS_SPEC §"Tab bar update" the bottom bar is now Queue /
    Today / Documents / Profile. Activity is reachable from Profile →
    Activity (linking the existing /audit route). Users who had muscle
    memory for the old 4th tab will need to re-learn one click; the
    Profile row is highlighted in info-tone to make the relocation
    discoverable.

23. **`(invisible)` — react-markdown brings ~50 KB to the detail page**
    /documents/[id] First Load JS = 258 KB (vs 142 KB for /today).
    Acceptable for an artifact viewer, but worth a code-split if other
    pages start rendering markdown. The renderer is also gated by
    rehype-sanitize default schema so agent output is never trusted
    with raw HTML.

24. **`(invisible)` — running `next build` while `next start` is alive
    leaves stale vendor chunks in the running process**
    The currently-running production server on port :3000 referenced
    `./vendor-chunks/zod.js` and started 500ing on dynamic routes after
    I ran `next build` mid-session. A clean `rm -rf .next && next build
    && next start` recovers; the server simply needs a restart. The
    build itself is clean (verified by booting a parallel `next start`
    on :3099 — every Documents route returns 200).

## Phase E — Final UX polish (feat/ux-polish)

25. **`(visible-tolerable)` — onboarding 4th card always shows, regardless
    of Telegram pairing status**
    The new 4th card ("Chat with Quill on Telegram") is shown to every
    user on first login, not just users already paired. Decision: the
    bot is universally useful and the card invites pairing rather than
    reporting state, so it works equally well in both situations. Future
    iteration could branch the copy: "Tap @DC_QuillBot to start" for
    unpaired users vs. "@DC_QuillBot is ready when you are" for paired.

26. **`(invisible)` — onboarding overlay is still browser-local (LS flag)**
    Carry-over from Phase A item 14: `localStorage.quill.onboarded` is
    per-browser. Adding the 4th card doesn't change that. Server-side
    onboarding completion remains a future-sprint concern.

27. **`(visible-tolerable)` — DocumentsFilterSheet operates client-side**
    The new filter sheet on /documents narrows the *current* result set
    (the API list query and FTS results) rather than re-issuing a server
    query with the new constraints. For the current dataset sizes
    (`limit=100` on list; FTS returns top-K matches) this is
    indistinguishable, but a power user filtering across thousands of
    docs would want server-side filtering. Future: extend `useDocuments`
    to accept the multi-axis params.

28. **`(visible-tolerable)` — Print from the more-menu prints the entire
    page including chrome**
    `MoreMenuSheet` calls `window.print()` after the sheet animates out,
    which uses the default browser print stylesheet. The bottom tab bar
    + top app bar are still in the printout. A dedicated `@media print`
    rule that hides chrome and prints just the document body is a polish
    follow-up.

29. **`(invisible)` — toast errors deliberately drop raw API messages**
    Phase E commit 3 replaced raw `e.message` toasts with plain-English
    copy across login, biometric prompt, passkey registration, approval
    decisions, and trust-tier changes. Raw errors are still
    `console.error`'d for developer triage; future work that wants the
    raw message for a power-user/debug path should use the console
    output, not the toast.

30. **`(invisible)` — shared skeleton primitives in components/ui/skeletons.tsx**
    Phase E commit 2 added shared `SkelBar` / `SkelListRow` / `SkelList`
    / `SkelCard` / `SkelSectionCard` / `SkelHeroCard` primitives. The
    pre-existing inline `SkeletonRows` in /audit and /documents pages
    were left as-is to keep the diff small; they could be migrated to
    the shared primitive in a future cleanup.

31. **`(visible-tolerable)` — onboarding overlay does not deep-link to
    Telegram**
    The 4th onboarding card mentions @DC_QuillBot but doesn't render the
    Telegram link as tappable text or a button. Showing it as static
    copy keeps the card calm; future iteration could add a small
    secondary button "Open Telegram" that fires `tg://resolve?domain=DC_QuillBot`.

32. **`(visible-tolerable)` — Gantt schedule is anchored on "today", not
    the project start**
    Phase G.2 ships `frappe-gantt` for the Schedule tab on
    cost_schedule_package documents. The schema doesn't store explicit
    activity start dates (just durations + predecessors), so the UI
    resolves the network topologically and anchors the project on
    today's UTC date. This makes the chart shape correct (durations,
    relationships, critical-path styling) but the absolute dates are
    illustrative — the agent doesn't know the real project start yet.
    A `metadata.project_start_date` field on the package would fix this
    cleanly.

33. **`(visible-tolerable)` — CSV / XER export is disabled when the
    artifact metadata doesn't carry an `upload_id`**
    The export endpoints live under `/v1/estimates/{upload_id}/export`,
    so the EstimatePackageDetail UI only enables the buttons when
    `metadata.upload_id` is present. The current API doesn't always
    propagate `upload_id` into the published artifact metadata; until
    it does, users opening a package directly from /documents will see
    the export button greyed out. Workaround: navigate from
    /estimates/[upload_id] → published doc.

34. **`(visible-tolerable)` — passkey ceremony falls back gracefully if
    the user cancels**
    The /estimates/[upload_id] approval button calls
    `challengePasskey()` first; if the ceremony fails (cancelled / no
    credential), we still issue the start_estimation request without an
    auth assertion. The API will reject the call with 401 if it
    requires the assertion — at which point we surface the error toast.
    A nicer flow would be to detect "no passkey registered" up-front
    and prompt registration before the user hits "Approve".

35. **`(invisible)` — frappe-gantt CSS is co-located in `components/
    estimates/frappe-gantt.css`**
    `frappe-gantt`'s package.json exports field forbids direct CSS
    imports under Next 14's bundler. We copied the bundled CSS into the
    repo so we can `import "./frappe-gantt.css"` from a client
    component. If we bump the dep, the CSS file may need a refresh.
