# Quill Copy Guide — Plain English

**Audience:** Project managers, owners, partners. **Not developers.** They've never heard the word "agent" in this context. They know construction. Write to them.

## Voice

- **Direct.** "RFI 247 needs your sign-off" — not "Approval item pending Lane 2 disposition."
- **Confident, not bureaucratic.** "We flagged this as cost impact" — not "Cost impact materiality threshold triggered."
- **Use the user's vocabulary.** "Approve / Reject / Edit" — yes. "Lane 2," "trust tier," "ceremony" — no.
- **Short sentences.** Most labels under 5 words; most explanations under 20.
- **Sentence case for everything except true proper nouns** (people, projects, products).

## Universal renames

These technical terms appear throughout the UI. Replace globally — UI-side only, don't change API contracts.

| Old (technical) | New (plain English) | When |
|---|---|---|
| Lane 1 / `tier-2-auto` | "Auto-handled" | Status / filter labels |
| Lane 2 / `tier-1-spotcheck` | "Needs your sign-off" | Default queue context |
| Lane 3 / `tier-0-mandatory` | "Needs two signatures" | Approval requiring partner |
| Mandatory / Spot-check / Auto (segmented control) | "Yours" / "Auto" / "Two-signer" — three segments. (Or three single-word labels like "Action" / "Auto" / "Approve & Co-sign" — pick one and stick to it.) | Lane segmented control |
| Agent | "Helper" or just the agent's display name (see "Agent display names" below) | When referring to the AI |
| Approval item / Approval | "Item" or the specific noun (RFI / submittal / report / ...) | List / detail headings |
| `confidence: 0.78` | "78% confident" or "Confidence: 78%" | Detail view |
| `agent_reasoning` | "Why we flagged this" | Detail label |
| `proposed_action.payload` | "What we're going to do" | Detail label |
| `prompt_version` | (hide unless user is in dev mode) | — |
| Audit log / Audit chain | "Activity log" — but keep "Activity" as the tab name; "log" is dev-speak | Tab + page |
| Workflow | "Action type" | Filter |
| `escalation_reasons` | "Why this is flagged" | Detail |
| Trust tier | "Trust level" — Probation / Standard / Trusted | Profile/agents page |
| `Mirror status` / "B2 mirror" | "Backup status" | Audit page |
| `verify_chain` / "Hash chain" | "Verify activity log" | Action button |
| RP ID / WebAuthn / passkey ceremony | Just say "passkey" or "Face ID / Touch ID" | Auth flows |
| `monthly_token_budget` | "Monthly budget" | Agent admin |

## Agent display names

API returns `agent_id` like `rfi-triage`. UI must show a human name + a one-line description.

| `agent_id` | Display name | One-liner |
|---|---|---|
| `coordinator` | "Quill Coordinator" | "Routes work to the right helper." |
| `rfi-triage` | "RFI Sorter" | "Reads new RFIs and routes them to the right discipline." |
| `rfi-drafter` | "RFI Responder" | "Drafts the answer to an RFI for your review." |
| `submittal-triage` | "Submittal Sorter" | "Checks submittal packages for completeness." |
| `submittal-spec-validator` | "Spec Checker" | "Confirms a submittal meets the spec, line by line." |
| `procurement-watch` | "Procurement Watcher" | "Tracks long-lead equipment and flags slip risk." |
| `daily-brief` | "Daily Brief" | "Builds your morning summary." |
| `dfr-synthesizer` | "Daily Field Report Reader" | "Reads field reports and updates the schedule." |
| `safety-aggregator` | "Safety Watcher" | "Pulls together safety observations and trends." |
| `progress-capture` | "Progress Capture" | "Reviews weekly site walks against the BIM model." |
| `co-estimator` | "Change Order Estimator" | "Estimates cost and schedule impact of design changes." |
| `ccb-prep` | "Change Board Prep" | "Builds the pack for the next change control board." |
| `owner-reporting` | "Owner Reporter" | "Drafts reports for the project owner." |
| `schedule-reader` | "Schedule Reader" | "Answers questions about the project schedule." |
| `critical-path-watch` | "Critical Path Watch" | "Flags any risk to the critical path." |
| `status-update-author` | "Status Update Author" | "Writes weekly status updates." |
| `project-coordinator` | "Project Coordinator" | "Maintains process docs, RACI, agendas." |
| `project-manager` | "Project Manager" | "Synthesizes scope, cost, schedule, risk." |
| `comms-drafter` | "Comms Drafter" | "Drafts owner / partner / sub messages." |
| `knowledge-manager` | "Knowledge Manager" | "Captures decisions for institutional memory." |

(The last 5 are forthcoming — see Phase C of the v3 expansion.)

A helper `lib/agent-meta.ts` should expose `displayName(agent_id)` and `description(agent_id)` so usage is consistent.

## Empty states (rewrite all of them)

Format: **friendly title + one-sentence subtitle + (optional) hint of what to do**.

### Queue tab
- Yours (Lane 2): "Nothing to sign off." / "When the helpers find something needing your eyes, it'll show up here."
- Two-signer (Lane 3): "No two-signer items." / "These are big-impact items that need both you and a partner."
- Auto (Lane 1): "Nothing handled automatically yet." / "Auto-handled items will show up here so you can spot-check anytime."

### Today tab (no data on first run)
- "Quill is still learning your project." / "Once the helpers have processed a day's work, you'll see your morning brief here."

### Audit / Activity
- "No activity yet." / "Every action Quill takes will be recorded here."

### Profile / Passkeys (none registered)
- "No passkeys yet." / "Add a passkey to sign in with Face ID or Touch ID."

## Inline help (small "?" icons)

Add an inline `?` icon next to these terms on first encounter. Tap reveals a short tooltip / sheet:

- **Lane / Yours / Two-signer / Auto** — "Items in 'Yours' need your sign-off only. 'Two-signer' items need you AND a partner — usually money or schedule changes. 'Auto' items the system handled automatically; you can review anytime."
- **Confidence (when shown numerically)** — "How sure the helper is about its recommendation. Below 70% means a human should look closely."
- **Activity log** — "A tamper-proof record of everything Quill has done. You can verify the integrity any time."
- **Backup status** — "Every action is saved locally and to an offsite backup. This shows the backup is up to date."
- **Trust level** — "How much autonomy this helper has earned. New helpers always require sign-off; trusted ones can do routine work automatically."

## Detail screen rewrites (the approval sheet)

Currently the sheet leads with technical fields. Restructure:

**Top of sheet (the lede):**
1. **Big plain-English title.** "RFI 247 — chiller dunnage conflict" — not the workflow ID.
2. **One-line summary.** "The chiller spec needs 24" of dunnage but the structural drawings only show an 8" pad. Needs coordination."
3. **Recommended action with confidence.** "Route this to the MEP engineer of record. (89% confident)"

**Why panel (collapsed by default, tap to expand):**
- "Why we flagged this" (the agent_reasoning text)
- "What we're proposing" (a clean read of `payload`, like "Assign to: MEP-EOR")
- Citations (with their excerpts, named clearly: "Spec section 23 64 16", "Drawing S-104")

**Flag chips (visible inline, plain language):**
- 💲 "Cost impact" instead of "$$"
- ⏱ "Schedule impact"
- ⚠ "Safety flag"
- ⏳ "Long-lead equipment"

**Action bar (bottom, sticky):**
- "Send back" (red ghost) — was "Reject"
- "Edit & approve" (gray ghost) — was "Edit"
- "Approve" (blue filled, primary)

## Tab names

Bottom tab bar — keep current names but verify they pass the "non-tech-savvy person" test:

| Current | Verdict | New |
|---|---|---|
| Queue | OK | Keep |
| Today | OK | Keep |
| Audit | Too technical | "Activity" |
| Profile | OK | Keep |

## Onboarding overlay (first login only)

Once: a 3-step swipe-through overlay after first successful login. Each step is one sentence + one image / icon.

1. **"Quill is your project assistant."** — A panel of helpers reads incoming work and prepares it for your sign-off.
2. **"Tap Approve, Reject, or Edit on any item."** — You're always in control. Nothing happens without your sign-off.
3. **"Use Today for a daily summary."** — At 7 AM, you'll get a brief of what needs your attention.

After the third panel, "Got it" button → /queue. Stored as `quill.onboarded=true` in localStorage.

## Loading & error states

### Loading
- Skeleton rows are fine. **No "Loading…" text.**
- For long operations (passkey ceremony, verify chain), show: skeleton + a small line of body text — "Verifying activity log…" — never "Please wait" or "Working on it."

### Error
- Lead with what happened in plain language.
- Provide an action: "Try again" or "Reload."
- Examples:
  - "Couldn't load your queue." / "Try again." (button)
  - "Sign-in didn't work — your passkey wasn't recognized." / "Try again."
  - "Couldn't reach Quill. Check your connection." / "Reload."

## Accessibility / honesty

- If a feature is mocked or stubbed, label it. "Calendar — coming soon" is better than showing fake events.
- Never use language that overstates Quill's autonomy: "I'll handle this" is wrong; "Routed for your sign-off" is right. Quill never *does*; it *proposes*, the human *approves*.
