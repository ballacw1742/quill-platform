# Quill UI Redesign Brief — iOS Home Screen Model

**Date:** 2026-07-06 · **Author:** Axe · **Status:** APPROVED by Charles (2026-07-06) — decisions locked, implementation underway

## 1. Goal

Replace the bottom tab bar + "More" sheet with an **iOS-style home screen**: a 3×5 grid of module icons, a **floating Home button** present in every module, and a **Requests hub that can reach every module's agents**. Restyle the whole app to Apple's latest design language (iOS 26 "Liquid Glass") so it feels like a real, crisp, native app — ready for outside users.

## 2. Design language

Base: Apple's current design resources (iOS 26 HIG + Liquid Glass material system), adapted for web:

- **Typography:** Apple system stack (already in place) with strict HIG type scale — Large Title 34, Title 28/22, Headline 17 semibold, Body 17, Footnote 13, Caption 11-12. No truncated or crowded labels anywhere.
- **Materials:** Liquid Glass — translucent, blurred, layered surfaces (`backdrop-filter`) for the floating button, headers, and sheets. Solid grouped backgrounds for content (iOS grouped-list style, largely already present).
- **Color:** System palette, light + dark mode. One accent tint across the app (default: iOS system blue; happy to swap — open decision #3). Semantic colors for status (green/amber/red) unchanged.
- **Icons:** SF-Symbols-style line icons (current lucide set restyled to consistent weight) inside **squircle tiles** with per-module gradient tints — like iOS app icons.
- **Motion:** Spring-based transitions (tile press → scale 0.96, page push/pop slide, sheet spring). Subtle, fast, never gimmicky.

## 3. New Home Screen (`/home`, becomes the app root)

**Layout, top to bottom:**
- Greeting header ("Good morning, Charles") + date, profile avatar top-right → opens Profile / Settings / Dev tools / Sign out.
- Compact **Today strip**: pending approvals count, open requests, one-line daily brief — tappable.
- **3×5 icon grid** (15 squircle tiles, label under each, badge counts where relevant — e.g. Approvals):

| | | |
|---|---|---|
| Requests | Approvals | Projects |
| Sites | Contracts | Estimates |
| Documents | Operations | Sales |
| Customers | Supply Chain | Finance |
| Compliance | Intelligence | Agents |

- **Roster note:** the app has 18 destinations today. Proposal: Today folds into the home header strip; Profile/Settings/Dev-chat move behind the avatar. That yields exactly 15 tiles (open decision #1).
- Grid is responsive: 3 columns on phone, scales spacing on tablet/desktop (max-width container, centered) — tiles never stretch or crowd.

## 4. Floating Home Button

- Circular **Liquid Glass** button (56pt) with a home icon — translucent blur + hairline border, adapts to light/dark. **Not** a solid color block like the reference image.
- Fixed bottom-center, above the safe-area/home-indicator. Present in **every module**, hidden on the home screen itself.
- Press = spring scale + haptic-style feedback, navigates home. Long-press (nice-to-have): quick-switcher sheet of the 15 modules.
- **No-overlap guarantee (audited per module):**
  - Every page gets bottom scroll padding ≥ button height + margin, so no content, list row, or action button can ever sit underneath it.
  - Toasts move above the button (offset adjusted); bottom sheets slide **over** it (button dims out while a sheet is open); sticky footer CTAs (e.g. approve/decline bars) get re-inset so the button never covers an action.

## 5. Requests Hub — every module represented

Today the Requests page is a composer with an agent picker. Redesign into a true **command center**:

- **Universal composer** stays on top — type anything, auto-classified to the right agent (current behavior preserved).
- Below it, an **action catalog grouped by module**: one horizontal row per module (all 15), each with concise action chips ("Draft RFI reply", "Estimate change order", "Flag at-risk customers", "Compliance deadlines"…) sourced from the agent registry's handled intents — so **all 30 agents are reachable from one screen**, and new agents appear automatically.
- Tapping a chip pre-fills the composer with that intent + a template prompt; user edits and sends.
- Recent requests list below, grouped by day, with status pills (running / needs approval / done) — unchanged functionally, restyled.

## 6. App-wide polish pass (the "real app" bar)

- Remove tab bar + More sheet everywhere; module pages get iOS large-title headers with back → home affordance.
- Sweep all 15 modules for: buttons that do nothing, text truncation/overflow at 375px width, inconsistent spacing, missing empty/loading/error states, contrast (WCAG AA), touch targets ≥ 44pt.
- Verify light + dark mode on every screen.
- Everything keyboard/desktop friendly too (this is a web app people may open on laptops).

## 7. Acceptance checklist (what "done" means)

1. Home grid: 15 tiles, 3×5, correct icons/labels/badges, nothing clipped at 375px → 1440px.
2. Floating Home button on every module, overlapping nothing, verified per module (screenshot audit).
3. Requests hub exposes actions for **all 15 modules / 30 agents**; every chip produces a valid request end-to-end.
4. No dead buttons, no hidden/crowded text, all states styled (loading/empty/error).
5. Light + dark verified; FE build clean; full test suite green; deployed and smoke-tested on the live URL.

## 8. Implementation plan

- **Phase 1 — Foundation:** design tokens (Liquid Glass materials, tint, type scale), squircle tile + floating button components. 
- **Phase 2 — Home screen + nav swap:** new root, remove tab bar, per-module bottom-inset audit.
- **Phase 3 — Requests hub redesign.**
- **Phase 4 — Module polish sweep + QA + deploy.**

Estimated effort: 3–4 focused sub-agent sprints; each phase ships behind main and is verified live before the next starts.

## 9. Decisions (locked by Charles, 2026-07-06)

1. **Grid roster** — Approved as proposed: 15 tiles; Today folds into the home header strip; Profile/Settings/Dev behind the top-right avatar.
2. **Home button placement** — Bottom-center.
3. **Accent tint** — Quill brand color: **"Quill Ink" indigo** (light `#5856D6`, dark `#5E5CE6` — Apple's indigo pair, so it stays native-feeling while being distinctly Quill, and works in both modes).
4. **Desktop layout** — Same home-grid model at all breakpoints (centered, max-width container).
