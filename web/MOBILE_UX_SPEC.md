# Quill Mobile UX — Per-Screen Wireframe Spec

**Companion to:** DESIGN_SYSTEM.md (must follow in lockstep). This file describes WHAT each screen contains and HOW navigation flows. The build subagent reads this and the design system together.

**Target device:** iPhone, 375–430 px wide, vertical orientation, Safari.

---

## App shell

```
┌─────────────────────────────┐
│  [Top bar: dynamic]         │  44 px + safe-top
├─────────────────────────────┤
│                             │
│  Screen content             │  flex-1, scrollable
│                             │
│                             │
├─────────────────────────────┤
│  [Tab bar]                  │  49 px + safe-bottom
└─────────────────────────────┘
```

Tab bar is **always visible** when authenticated. 4 tabs:

1. **Queue** (`Inbox` icon) — default tab, where work happens
2. **Today** (`Sparkles` icon) — Daily Brief view (new)
3. **Audit** (`History` icon) — chain log + verifier
4. **Profile** (`User` icon) — settings, passkeys, agent fleet, health

Active tab: icon + label in `--accent`. Inactive: `--label-secondary`.

---

## Authentication (entry)

### `/login`

Minimal. No marketing copy.

**Layout, top to bottom (centered, generous vertical space):**

1. Quill wordmark, 48 px tall, `--label-primary` (currently a ShieldCheck icon — keep that, but bigger and centered).
2. **Title** `text-title-1`: "Sign in"
3. **Subtitle** `text-body` `--label-secondary`: "Use your passkey to continue."
4. Email input. `text-body`. Placeholder: "you@example.com". Pre-filled with the last successful login email if there was one.
5. **Primary button:** "Sign in with passkey". Full-width, 50 px, `--accent` filled, `text-headline 600`. Triggers passkey ceremony.
6. **Ghost link below button:** "Register a passkey" — opens passkey registration sheet. Smaller, `--accent`, `text-callout`.
7. **Dev fallback (only if `NEXT_PUBLIC_DEV_AUTH_FALLBACK=1`):** A small `<details>` collapsed by default reading "Developer sign-in" with an inset password field + "Sign in" button. Hidden in production.

No "Welcome to Quill" hero. No tagline below the form. No footer link to docs. The form is the screen.

### `/settings/passkeys` (later, accessed via Profile tab)

iOS-style grouped list:

- Section header (small caps, `text-caption-1`, label-secondary): "Passkeys"
- Each registered passkey is a list row: device name + "Last used 2 days ago". Tap shows detail sheet with revoke option.
- Footer button: "Add passkey" — full-width tinted `--accent`, opens registration ceremony.

---

## Tab 1 — Queue

The most-used screen. Optimize for "see → decide → next."

### `/queue`

**Top bar:**
- Title `text-title-1` left-aligned: "Queue"
- Right-side counter: `text-callout`, `--label-secondary` — "26 pending"
- Right-side icon button: `SlidersHorizontal` (filter sheet)

**Lane segmented control** (right under top bar):
- iOS-style segmented control with 3 segments: "Mandatory" / "Spot-check" / "Auto"
- Each segment shows the lane's count as a small chip
- Selected segment uses elevated `--bg-tertiary` background
- Default: Spot-check (Lane 2) since that's the workflow Charles lives in

**Below the segmented control:**
- Pull-to-refresh enabled (drag down, sees a spinner, releases, refetches)
- Search bar (collapsed by default; tap a search icon in the top bar to expand)
- List of approval rows for the active lane

**Approval row (compact list item):**

```
┌──────────────────────────────────────────────────────┐
│ [icon]  Title in 17/600 (max 1 line)        [chip]  │
│         Subtitle in 15/400 (max 2 lines)            │
│         flag-chips · age                            │
└──────────────────────────────────────────────────────┘
```

- **Icon:** small 20 px agent badge (initials or a `lucide` icon mapped per agent)
- **Title:** the workflow human-readable name + key reference (e.g., "Triage RFI-BLDG4-1697")
- **Subtitle:** the agent-generated `summary` field, 2-line ellipsis
- **Flag chips:** small caps in `text-caption-1` — "$$" for cost, "⏱" for schedule, "⚠" for safety. Use the colored dot+label pattern, not gradients.
- **Age:** "2h ago" right-aligned, `text-footnote`, `--label-tertiary`
- **Tap:** opens detail sheet
- **Swipe left:** reveals "Approve" (green) and "Reject" (red) — only for Lane 2 standard items
- **Swipe right:** reveals "Open" (just opens the detail sheet — for parity)

**Empty state per lane:**
- `Inbox` icon, 56 px, `--label-tertiary`
- "No pending items"
- `--label-secondary` subtitle: "When agents drop new work, it lands here."

### Approval detail sheet (slides up over Queue)

Slides up from bottom on row tap or "Open" swipe.

```
┌─────────────────────────────────────────┐
│       ────  drag handle                 │
│                                         │
│  Cancel        Title           Open in… │  ← top bar inside sheet
│                                         │
│                                         │
│  [Big card: AGENT'S RECOMMENDATION]     │
│                                         │
│  Triage classification                  │
│  Discipline · MEP                       │
│  Spec · 26 13 13                        │
│  Confidence · 88%                       │
│  Suggested assignee · MEP-EOR           │
│                                         │
│  ────────  separator                    │
│                                         │
│  CONTEXT                                │
│  • RFI-BLDG4-1697 [↗]                   │
│  • Spec 26 13 13 [↗]                    │
│  • BLDG4-LV741 (drawing) [↗]            │
│                                         │
│  Reasoning · "RFI references..."        │
│                                         │
│  ────────                               │
│                                         │
│  AUDIT TRAIL                            │
│  Created 2h ago · agent:rfi-triage      │
│  ────────                               │
│                                         │
│         [empty space]                   │
│                                         │
├─────────────────────────────────────────┤
│  [Reject]  [Edit]      [Approve]        │  ← sticky bottom action bar
└─────────────────────────────────────────┘
```

- **Top bar inside sheet:** "Cancel" left (closes sheet), short title center ("Approval"), kebab/menu right with secondary actions ("Escalate", "Snooze", "View raw JSON")
- **Hero card (large):** the agent's headline recommendation in `text-title-3`. The most important fields styled clean as a small data table — label-secondary on left, label-primary on right.
- **Context section:** source artifacts as tappable rows (each opens an external sheet or copies the ID). Citations with excerpts.
- **Reasoning:** small italic block in `text-callout label-secondary` showing the agent's `agent_reasoning`.
- **Audit trail:** condensed timeline of events for this approval.
- **Sticky bottom action bar** (full-width): "Reject" ghost-danger / "Edit" ghost / "Approve" primary. **Tapping Approve triggers the passkey ceremony (full-screen overlay), and on success the sheet auto-dismisses.**

### Filter sheet (from the top-bar filter icon)

Slides up. Contains:
- Agent (multi-select chip list)
- Workflow (single-select)
- Age (segmented: "Any / < 1h / < 24h / > 24h")
- Priority (toggle pills)
- "Apply" primary button at the bottom; "Reset" ghost above it.

---

## Tab 2 — Today

**New screen.** Charles's morning operating page. Replaces the 7am Telegram brief in the web context.

### `/today`

**Top bar:**
- Title `text-large-title`: "Today"
- Subtitle below `text-headline label-secondary`: full date — "Friday, May 8"
- (No right-side button.)

**Hero card — Top of Mind:**
- `--bg-tertiary`, padded, `radius-xl`.
- Heading `text-title-3`: "Top of mind"
- Up to 3 items, each one row:
  - `text-headline` (item headline)
  - `text-callout label-secondary` (why it matters)
  - Small action chip ("Review", "Acknowledge", "Decide")

**Below the hero, stacked sections (each is a tappable card row):**

1. **Approvals waiting** — count + lane breakdown chips. Tap → goes to /queue with filter applied
2. **Critical path** — top 1-2 risks; "View all" tap opens a list
3. **Procurement watch** — number of alerts; tap → sheet with detail
4. **RFIs aged > 48h** — count, tap → filtered queue
5. **Hyperscaler inbox** — count; tap → list
6. **Today's calendar** — first 3 events, each a row with time + title

**Footer (small):** "Last refreshed 14 sec ago" + manual refresh icon button.

If Daily Brief agent has run, show "Brief delivered to Telegram at 7:00 AM ET" as a subtle status row.

If no data yet (first run), empty state: "Quill builds your daily brief from agent activity. Check back tomorrow morning."

---

## Tab 3 — Audit

Less day-to-day, but critical for trust and disputes.

### `/audit`

**Top bar:**
- Title `text-title-1`: "Audit"
- Right: filter icon

**Hero card — Chain integrity:**
- Status indicator: green dot + "Chain verified" OR red dot + "Drift detected"
- Last verified: "12 min ago"
- Total entries count
- "Verify now" primary button (manual trigger)
- Mirror status row (B2 / local / lag)

**Below: searchable / filterable list of audit entries:**

Each entry is a list row:
```
[icon]  approval.created · agent:rfi-triage           2h ago
        approval-id: cea8dbed-… → tap to copy
        sha256: 023d7560bff…
```

- Icon mapped per event_type (created → `Plus`, decided → `CheckCircle`, executed → `Send`, etc.)
- Tap row → expand sheet showing full event payload + hash chain context
- Long-press → copy hash to clipboard (mobile pattern)

**Filter sheet from filter button:**
- Event type
- Actor
- Time range
- Approval ID search

### Verification result sheet (after "Verify now")

- Big result tag at top: green "Verified ✓" or red "Drift detected"
- Stats: "Verified 50 / 50 entries" — chain length, last hash, duration
- If failures: list of offending entry IDs with details
- Close button bottom

---

## Tab 4 — Profile

Catch-all for personal settings + admin views that don't deserve their own tab.

### `/profile`

iOS-style grouped list, 4 sections:

**Section 1 — Account:**
- "Charles Mitchell" (display_name, `text-headline`)
- "charles@quill.local" (label-secondary)
- "Owner" role chip
- Tap → expanded sheet with edit display name etc.

**Section 2 — Authentication:**
- "Passkeys" → `/profile/passkeys` (manage credentials)
- "Sign out" (ghost-danger color)

**Section 3 — Telegram:**
- If paired: "@DC_QuillBot" + paired chat ID + "Unpair" action
- If unpaired: "Pair Telegram" → opens pairing instructions sheet

**Section 4 — Quill (advanced/admin):**
- "Agents" → `/profile/agents` (was the standalone Agents tab)
- "Fleet health" → `/profile/health` (was the standalone Health tab)
- "Settings" (theme, notifications, etc.)
- "About Quill" (version, build, links)

### `/profile/agents`

Same content as the existing `/agents` page but redesigned:
- Top bar with back chevron and "Agents"
- Grouped list per agent showing: name, version, trust tier badge, default lane, last active, monthly token budget bar
- Tap row → sheet with promote/demote actions and audit log of recent activity for this agent

### `/profile/health`

Same content as the existing `/health` page but redesigned:
- Big status card up top: green/yellow/red dot + "All systems normal" / "Degraded" / "Issues detected"
- Below: list of subsystems
  - Queue depth (linked to /queue)
  - Audit chain (linked to /audit)
  - Anthropic API status
  - On-prem inference (n/a)
  - Spend MTD with progress bar against budget

---

## Cross-cutting flows

### Passkey ceremony (used during register, login, every approval decision)

Full-screen overlay (NOT a sheet — covers everything including tabs):
- Centered: large `Fingerprint` icon (or a SF Symbols-style touch ID glyph), 64 px
- Title `text-title-2`: "Confirm with passkey"
- Subtitle `text-body`: depends on context — "Approve RFI-DC1-A-0247", "Sign in to Quill", etc.
- Countdown: "Expires in 47s" small, `text-footnote label-secondary`
- Primary button: "Use passkey" (triggers `navigator.credentials.get(...)`)
- Cancel ghost button below
- iOS biometric prompt fires natively from the OS — that's the actual auth UI, our screen is the framing

### Toast / alert positions

Bottom-anchored above tab bar. 12 px from tab bar top edge. 12 px horizontal margin. Slide up + fade.

### Error states (network / server)

When a fetch fails (not 401 — that's handled silently), show inline within the affected card or screen:
- Small banner at the top of the failed section
- `--bg-elevated`, `--danger` accent left-border
- Body text + "Try again" ghost button on the right
- Don't replace the entire screen with an error page; let the rest of the UI keep working

---

## Hard rules for the implementer

1. **Don't add new pages or routes** beyond what's specified here. If you think one is needed, surface it instead of building it.
2. **Don't change the API contracts.** Use the existing TanStack Query hooks (already adapted). If you need a new field, surface it.
3. **Don't keep any of the current page layouts.** Rebuild from this spec. The current AppShell, the 3-column queue, the desktop-first detail page — all out.
4. **Replace primitives where needed.** The existing `components/ui/*` Radix-based primitives mostly work for desktop. Mobile-targeted primitives (Sheet from bottom, segmented control, swipe-action row) need new components.
5. **Animations use framer-motion or pure CSS.** Pick one and stay with it. Don't mix.
6. **Test in mobile Safari (the actual target).** The build is not done until at least the queue, today, audit, and profile tabs render and function on iPhone Safari at 390 px width.

---

## Out of scope this sprint (for the implementer's clarity)

- Edit-payload diff editor — keep the existing simple diff for now; don't redesign
- Agent fleet detail page interactions — surface existing data, don't build new flows
- Multi-user / partner approver UI
- Notifications center inside the web app (we have Telegram for that)
- Customizable themes (just light + dark per system)
