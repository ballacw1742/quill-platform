/**
 * lib/help-content.ts — short explanations for inline `?` help icons.
 *
 * Per COPY_GUIDE.md §"Inline help (small `?` icons)":
 * each entry is a {title, body} pair, where `body` is one or two short
 * paragraphs in plain English. Tone: direct, sentence-case, no jargon.
 *
 * Used by `components/ui/help-hint.tsx`.
 *
 * To add a new term:
 *   1. Pick a short snake-case key (lane, confidence, ...).
 *   2. Add it here with a 1–2 sentence explanation.
 *   3. Drop `<HelpHint term="your-key" />` next to the term in the UI.
 */

export type HelpEntry = {
  /** Short heading shown at the top of the help sheet. */
  title: string;
  /** One or two short paragraphs (plain text — no markdown). */
  body: string[];
};

export const HELP_CONTENT: Record<string, HelpEntry> = {
  lane: {
    title: "What do these tabs mean?",
    body: [
      "Items in Yours need your sign-off only.",
      "Two-signer items need you AND a partner — usually money or schedule changes.",
      "Auto items the system handled automatically. You can review them any time.",
    ],
  },
  confidence: {
    title: "What does the percentage mean?",
    body: [
      "How sure the helper is about its recommendation.",
      "Below 70% means a human should look closely before approving.",
    ],
  },
  activity_log: {
    title: "What is the activity log?",
    body: [
      "A tamper-proof record of everything Quill has done — every item created, every approval, every action.",
      "You can verify the integrity any time. If anything was changed after the fact, the verification will fail.",
    ],
  },
  backup_status: {
    title: "What is backup status?",
    body: [
      "Every action is saved locally and to an offsite backup.",
      "This shows the offsite backup is up to date.",
    ],
  },
  trust_level: {
    title: "What is trust level?",
    body: [
      "How much autonomy this helper has earned over time.",
      "New helpers always require sign-off. Trusted ones can do routine work automatically — but you can still spot-check anything in the Auto tab.",
    ],
  },
  escalations: {
    title: "Why is this flagged?",
    body: [
      "Flags call out anything that needs your attention — cost impact, schedule impact, safety, long-lead equipment, or critical-path risk.",
      "If a helper isn't sure, it errs on the side of flagging.",
    ],
  },
};

/**
 * Resolve a help key → entry, with a graceful fallback so the UI never
 * shows a missing-content state.
 */
export function getHelp(term: string): HelpEntry {
  const hit = HELP_CONTENT[term];
  if (hit) return hit;
  return {
    title: "About this",
    body: ["More information is on its way."],
  };
}
