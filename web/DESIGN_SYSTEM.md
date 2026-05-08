# Quill Mobile UI — Design System (locked contract)

**Status:** Authoritative. The build subagent reads this file and follows it line-by-line. Do not improvise.

**Target:** iPhone Safari (375–430 px). Desktop (md+) is a "responsive bonus" but mobile is the primary case.

**Aesthetic goal:** "If Apple shipped a project-management app." Calm, dense-when-needed, generous-when-not, monochromatic with one accent color, native-feeling motion. Looks at home next to Things 3, Linear iOS, Mail, Reminders, Calendar.

---

## 1. Foundational principles

1. **Mobile-first.** Default layout assumes 390 px width. Tab bar at the bottom. Primary actions reachable by thumb.
2. **One thing per screen.** No competing CTAs. The user always knows the answer to "what's the most important action right now."
3. **Density follows context.** Lists are dense (compact rows). Detail views are spacious. Approval ceremony is full-screen and unhurried.
4. **Motion is purposeful, never decorative.** Modal sheets slide up; queue items spring-out on swipe; nothing bounces. Everything finishes in ≤ 320 ms.
5. **Apple-native typography.** SF Pro via `-apple-system` stack. Apple's type scale, not Tailwind defaults.
6. **System color awareness.** Light mode and dark mode both first-class. Respect `prefers-color-scheme`.
7. **No filler chrome.** Charles isn't reading marketing copy. Delete every "Welcome to Quill" / "Get started" / motivational paragraph. Show data, show actions, get out of the way.

## 2. Color tokens

Use CSS custom properties. Tailwind reads them.

### Light mode

```css
--bg:                #FFFFFF;            /* App background */
--bg-elevated:       #F2F2F7;            /* Cards, list groups (iOS systemGroupedBackground) */
--bg-tertiary:       #FFFFFF;            /* Card on top of grouped bg */
--separator:         rgba(60,60,67,0.12);/* Cell dividers, hairlines */
--separator-opaque:  #C6C6C8;
--label-primary:     #000000;
--label-secondary:   rgba(60,60,67,0.60);
--label-tertiary:    rgba(60,60,67,0.30);
--label-quaternary:  rgba(60,60,67,0.18);
--accent:            #007AFF;            /* iOS systemBlue */
--accent-pressed:    #0062CC;
--success:           #34C759;            /* systemGreen */
--warning:           #FF9500;            /* systemOrange */
--danger:            #FF3B30;            /* systemRed */
--info:              #5856D6;            /* systemIndigo */
```

### Dark mode

```css
--bg:                #000000;
--bg-elevated:       #1C1C1E;            /* iOS systemGray6 dark */
--bg-tertiary:       #2C2C2E;
--separator:         rgba(84,84,88,0.65);
--separator-opaque:  #38383A;
--label-primary:     #FFFFFF;
--label-secondary:   rgba(235,235,245,0.60);
--label-tertiary:    rgba(235,235,245,0.30);
--label-quaternary:  rgba(235,235,245,0.18);
--accent:            #0A84FF;            /* iOS dark systemBlue */
--accent-pressed:    #409CFF;
--success:           #30D158;
--warning:           #FF9F0A;
--danger:            #FF453A;
--info:              #5E5CE6;
```

### Status mapping (use throughout the app)

| Quill concept | Color token |
|---|---|
| Pending Lane 1 (Auto) | `--label-tertiary` neutral |
| Pending Lane 2 (Single sig) | `--accent` |
| Pending Lane 3 (Dual sig) | `--warning` |
| Approved | `--success` |
| Rejected | `--danger` |
| Critical-path-flagged | `--danger` |
| Safety-flagged | `--danger` |
| Cost impact flagged | `--warning` |
| Informational | `--label-secondary` |

**No other colors.** No purple, no teal, no gradient unless explicitly approved by Charles.

## 3. Typography

Font stack:
```css
font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", system-ui, sans-serif;
```

### Type scale (matches iOS Dynamic Type "Body" base = 17px)

| Token | Size / Weight / Line-height | Usage |
|---|---|---|
| `text-large-title` | 34 / 700 / 41 | Top-of-screen titles, hero numbers |
| `text-title-1` | 28 / 700 / 34 | Page titles |
| `text-title-2` | 22 / 700 / 28 | Section headers |
| `text-title-3` | 20 / 600 / 25 | Subsection headers |
| `text-headline` | 17 / 600 / 22 | List item titles, button labels |
| `text-body` | 17 / 400 / 22 | Body copy |
| `text-callout` | 16 / 400 / 21 | Secondary copy, list subtitles |
| `text-subhead` | 15 / 400 / 20 | Captions |
| `text-footnote` | 13 / 400 / 18 | Metadata |
| `text-caption-1` | 12 / 400 / 16 | Badges, fine print |
| `text-caption-2` | 11 / 400 / 13 | Smallest acceptable |

Tailwind config exposes these as semantic classes (`text-body`, `text-headline`, etc.). **Never use raw `text-sm` / `text-xs` in Quill UI code.**

## 4. Spacing

Rhythm based on 4. Mobile-first values:

| Token | Value | Usage |
|---|---|---|
| `space-1` | 4 px | Inline gap between icon + label |
| `space-2` | 8 px | Tight list item padding-y |
| `space-3` | 12 px | Default list item padding-y |
| `space-4` | 16 px | Standard padding-x for screens; gap between cards |
| `space-5` | 20 px | Section padding-y |
| `space-6` | 24 px | Hero element vertical padding |
| `space-8` | 32 px | Top padding under nav bar |
| `space-12` | 48 px | Major section breaks |

Screen-edge horizontal padding is **always 16 px** (`space-4`). Cards have **internal padding 16 px**.

## 5. Radii & elevation

| Token | Value | Usage |
|---|---|---|
| `radius-sm` | 8 px | Small chips, badges |
| `radius-md` | 10 px | List items, secondary buttons |
| `radius-lg` | 12 px | Cards |
| `radius-xl` | 16 px | Sheets, modals, full cards |
| `radius-2xl` | 22 px | Large modal sheets (iOS sheet style) |

Shadows are **subtle**:
- `shadow-card`: `0 1px 2px rgba(0,0,0,0.04), 0 0 1px rgba(0,0,0,0.06)` (light); `0 0 0 1px rgba(255,255,255,0.05)` (dark)
- `shadow-elevated`: `0 4px 16px rgba(0,0,0,0.08)` for sheets/popovers

No ambient drop shadows on flat list items. Apple uses hairline borders, not shadows, for separators.

## 6. Motion

All transitions use this curve:
```
cubic-bezier(0.32, 0.72, 0, 1)  /* iOS spring approximation */
```

Durations:
- Tap feedback: 100 ms
- State changes (toggle, color): 200 ms
- Sheet slide up: 320 ms
- Sheet dismiss: 280 ms
- Page transitions: 240 ms

**Never use bouncy or elastic curves.** No springs > 1.0 overshoot. No rotate-on-load. No "wobble."

## 7. Component patterns

### Bottom tab bar (primary navigation)

- Always visible on mobile (≤ 768 px).
- 4 tabs: **Queue** · **Today** · **Audit** · **Profile**.
- Each tab: SF Symbols-style icon + small label; active tab uses `--accent` for icon and label.
- Height: 49 px content + safe-area-inset-bottom.
- Background: `--bg` with backdrop-blur (iOS-style translucency in light mode).
- Hairline border on top: 1 px `--separator`.
- Icons preferred: `lucide-react` (we already have it). Use `Inbox`, `Sparkles`, `History`, `User` (or similar).
- Use `<a>` not `<button>` so deep linking works.
- **Hide on desktop (md+);** desktop uses a left sidebar instead (not in scope for this sprint, but layout should not assume tab bar exists on desktop).

### Top app bar

- Optional. Use only on full-screen views inside a tab.
- Title: `text-headline` left-aligned, or `text-title-1` for page-hero variant.
- Optional left button (back chevron `<` for stack navigation, never a "menu" hamburger).
- Optional right button (compact action — single icon or short word like "Done").
- Background: `--bg`. Hairline `--separator` on bottom only when content scrolls underneath.
- Height: 44 px content + safe-area-inset-top.

### List rows (the workhorse)

This is the most-used component. Get it right.

- 56 px minimum tap height (Apple HIG: 44 px floor; we use 56 for thumb comfort).
- Layout: `[icon] [stack: title / subtitle] [chip] [chevron]`.
- Title: `text-headline`, label-primary.
- Subtitle: `text-callout`, label-secondary, max 2 lines, ellipsis.
- Chip (right): age, count, status — `text-footnote`, label-tertiary.
- Chevron `>`: only present if the row navigates to a detail view.
- Tap target is the entire row.
- Hairline separator between rows, indented to align with title (matches iOS Settings/Mail).
- Row inset: `space-4` left/right padding; in grouped lists, the row sits inside a card with `--bg-tertiary` background and `radius-lg`.

### Swipe actions on list rows

Match iOS Mail/Reminders pattern.

- **Swipe left → trailing actions** (most common): "Approve" (success green) and "Reject" (danger red).
- **Swipe right → leading actions** (less common): "Snooze" or "Open."
- Reveal threshold: 48 px partial reveal, 96 px full commit.
- Quick-swipe past 50% commits the primary action without requiring release.
- Use `framer-motion` `useDrag` or a tiny custom touch handler.
- Haptic feedback (where supported via `navigator.vibrate(10)`) on commit.

**Important:** swipe actions are **only enabled for Lane 1 and Lane 2 standard items**. Lane 3 (dual-sig) and any item flagged safety/critical-path requires tap-through to the full detail screen — too high stakes for swipe shortcuts.

### Buttons

| Variant | Use | Style |
|---|---|---|
| Primary | The single most important action on screen | Filled `--accent`, white text, `radius-lg`, 50 px tall, `text-headline 600` |
| Secondary | Alternative action | Tinted (low-opacity `--accent` background, full `--accent` text) |
| Ghost | Tertiary | No fill, just `--accent` text |
| Destructive | Reject / delete | Filled `--danger`, white text |

- Buttons stretch full-width on mobile by default.
- Padding-y 14 px on filled, 12 px on ghost.
- Tap state: opacity 0.85 with 100 ms transition.

### Cards

- `--bg-tertiary` background (subtle elevation against `--bg-elevated`).
- `radius-lg` corners.
- Internal padding `space-4`.
- Optional hairline top/bottom or full border using `--separator`.
- **No hover effects on mobile.** Hover is for desktop only and even there should be subtle.

### Sheets (the iOS modal pattern)

Used for: approval detail view, edit-payload editor, passkey ceremony, settings forms.

- Slide up from bottom.
- `radius-2xl 22 px` top corners only.
- Backdrop: 50% black overlay.
- Drag handle at top: 36 × 5 px capsule, `--label-quaternary`.
- Dismiss: tap backdrop OR drag handle down OR swipe down >100 px.
- Sheet height: content-driven up to 92% of viewport. Long content scrolls inside.
- Title bar inside sheet: short title, "Done" or "Cancel" on right.

### Empty states

- Center: SF-symbol-style line icon, 56 × 56, `--label-tertiary`.
- Title: `text-title-3`, `--label-primary`.
- Subtitle: `text-body`, `--label-secondary`.
- Optional action: ghost button.
- **Never** use a "Cool emoji 🎉" — Apple doesn't, neither do we.

### Loading states

- Skeleton rows with shimmer animation (1.4 s loop, opacity 0.4 → 0.7).
- Or `<ActivityIndicator>` (matches iOS `UIActivityIndicatorView`): a 24 px gray spinner, `--label-secondary`.
- **No "Loading..." text strings.** Show the skeleton, that's it.

### Toasts / alerts

- Use Sonner (already installed) but restyle:
- Background `--bg-tertiary`, hairline border `--separator`.
- 12 px rounded.
- Slide in from bottom, dismiss after 4 s or on tap.
- Position: bottom 80 px (above tab bar).

## 8. Iconography

- Library: `lucide-react` (already installed).
- Stroke width: 1.75 (matches SF Symbols default weight).
- Sizes: 16 / 20 / 24 / 28. No 14 or 18.
- Color: inherit from text (`currentColor`).
- Specific icon mapping (use these consistently):

| Concept | Icon |
|---|---|
| Queue | `Inbox` |
| Today / Brief | `Sparkles` or `Sun` |
| Audit | `History` or `FileClock` |
| Profile / Settings | `User` |
| Approve | `Check` |
| Reject | `X` |
| Edit | `Pencil` |
| Escalate | `ArrowUpRight` |
| Critical | `AlertTriangle` |
| Safety | `ShieldAlert` |
| Cost impact | `DollarSign` |
| Schedule impact | `Clock` |
| Long-lead | `Truck` |
| Pending | `CircleDot` |
| Approved | `CheckCircle2` |
| Search | `Search` |
| Filter | `SlidersHorizontal` |
| Refresh | `RotateCw` |

## 9. Forbidden patterns

These exist in the current Quill UI and must be removed:

- ❌ The hamburger / drawer nav. Use bottom tabs.
- ❌ "Toolbar" with 4+ filter dropdowns above the queue. Push filters into a bottom sheet behind a single "Filter" button.
- ❌ Three-column queue view on mobile. **Mobile shows one lane at a time** (segmented control or swipeable tabs at top to switch lanes).
- ❌ Tooltips of any kind on mobile (no hover).
- ❌ Right-side panel for approval detail. **Approval detail is a full-screen sheet from below.**
- ❌ Confetti, celebration animations, gradient backgrounds.
- ❌ "Quill" logo in the top-left of every page. Just on the login screen and the profile screen.
- ❌ Footer text on the login screen ("Approval queue for the Agentic PMO fleet"). Replace with nothing — let the form breathe.
- ❌ Visible "Sprint 1 stub" labels in production paths. (Keep them only for the dev-fallback section.)

## 10. Accessibility (non-negotiable)

- Tap targets ≥ 44 × 44 pt always.
- Color contrast meets WCAG AA against `--bg`. We're using iOS system colors so this is mostly handled.
- Focus rings visible on keyboard nav (desktop): 2 px `--accent` outline + 2 px offset.
- All icons have `aria-label` if the icon is the only content (e.g., icon-only back button).
- Screen reader: `<nav>`, `<main>`, `<aside>` landmarks. Lane tabs use `role="tablist"`. Sheets use `role="dialog" aria-modal="true"`.
- Respect `prefers-reduced-motion` — disable swipe spring animations; instant state change instead.
- Form inputs have visible labels (no placeholder-as-label).

## 11. Testing checklist

The build subagent verifies all of these before declaring done:

- [ ] Light mode + dark mode (toggle in DevTools)
- [ ] iPhone SE (375 px) and iPhone 15 Pro Max (430 px) widths
- [ ] Desktop sm/md (640/768) — no horizontal scroll, layout adapts
- [ ] Tab bar: stays at bottom, doesn't overlap content (use `pb-safe`)
- [ ] Top safe area handled (`pt-safe` on top bars)
- [ ] Swipe actions on Lane 2 row: left for approve, right for reject (both partial-reveal and fully-commit)
- [ ] Approval detail sheet: opens from bottom, drag-to-dismiss works
- [ ] No console errors / hydration warnings
- [ ] All 4 tabs reachable, all 4 render
- [ ] Empty state on each tab when there's no data
- [ ] Loading skeleton on first paint
- [ ] All flagged interactive elements have ≥ 44 × 44 pt tap area
- [ ] Reduced-motion toggle (DevTools → emulate `prefers-reduced-motion`) — no animations fire
- [ ] No raw text-sm / text-xs / text-2xl in any new code (use semantic tokens)

If any item fails, the build is not done.
