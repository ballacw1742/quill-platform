/**
 * lib/agent-meta.ts — UI display metadata for agent_id, lane, priority, etc.
 *
 * Per COPY_GUIDE.md, the API surface uses developer-friendly identifiers
 * (`rfi-triage`, `tier-1-spotcheck`, `prompt_injection_detected`, ...) that
 * mean nothing to a project manager. This module is the single source of
 * truth for translating those identifiers into the plain-English copy
 * shown in the UI.
 *
 * Voice rules (per COPY_GUIDE):
 *   - Direct, sentence-case, short.
 *   - Use the user's vocabulary — say "RFI", not "lane 2 spot-check item".
 *   - Never the word "agent" in user-facing surfaces; use the helper's
 *     display name or "helper" if generic.
 *
 * Lane vocabulary (note: API integer lane vs. prompt-tier string vs. UI label):
 *   API integer lane | prompt-tier string  | UI label             | UI tab label
 *   1                | tier-2-auto         | "Auto-handled"       | "Auto"
 *   2                | tier-1-spotcheck    | "Needs your sign-off"| "Yours"
 *   3                | tier-0-mandatory    | "Needs two signatures" | "Two-signer"
 *
 * Unknown values fall back to a pretty-cased version of the input
 * (turning `foo_bar-baz` into `Foo bar baz`) so we never leak a raw token.
 */

// ── Agent display names ─────────────────────────────────────────────────────

export type AgentDisplay = { name: string; description: string };

/**
 * Canonical agent_id → human-friendly display.
 * Source: COPY_GUIDE.md §"Agent display names".
 */
export const AGENT_DISPLAY: Record<string, AgentDisplay> = {
  coordinator: {
    name: "Quill Coordinator",
    description: "Routes work to the right helper.",
  },
  "rfi-triage": {
    name: "RFI Sorter",
    description: "Reads new RFIs and routes them to the right discipline.",
  },
  "rfi-drafter": {
    name: "RFI Responder",
    description: "Drafts the answer to an RFI for your review.",
  },
  "submittal-triage": {
    name: "Submittal Sorter",
    description: "Checks submittal packages for completeness.",
  },
  "submittal-spec-validator": {
    name: "Spec Checker",
    description: "Confirms a submittal meets the spec, line by line.",
  },
  "procurement-watch": {
    name: "Procurement Watcher",
    description: "Tracks long-lead equipment and flags slip risk.",
  },
  "daily-brief": {
    name: "Daily Brief",
    description: "Builds your morning summary.",
  },
  "dfr-synthesizer": {
    name: "Daily Field Report Reader",
    description: "Reads field reports and updates the schedule.",
  },
  "safety-aggregator": {
    name: "Safety Watcher",
    description: "Pulls together safety observations and trends.",
  },
  "progress-capture": {
    name: "Progress Capture",
    description: "Reviews weekly site walks against the BIM model.",
  },
  "co-estimator": {
    name: "Change Order Estimator",
    description: "Estimates cost and schedule impact of design changes.",
  },
  "ccb-prep": {
    name: "Change Board Prep",
    description: "Builds the pack for the next change control board.",
  },
  "owner-reporting": {
    name: "Owner Reporter",
    description: "Drafts reports for the project owner.",
  },
  "schedule-reader": {
    name: "Schedule Reader",
    description: "Answers questions about the project schedule.",
  },
  "critical-path-watch": {
    name: "Critical Path Watch",
    description: "Flags any risk to the critical path.",
  },
  "status-update-author": {
    name: "Status Update Author",
    description: "Writes weekly status updates.",
  },
  "project-coordinator": {
    name: "Project Coordinator",
    description: "Maintains process docs, RACI, agendas.",
  },
  "project-manager": {
    name: "Project Manager",
    description: "Synthesizes scope, cost, schedule, risk.",
  },
  "comms-drafter": {
    name: "Comms Drafter",
    description: "Drafts owner / partner / sub messages.",
  },
  "knowledge-manager": {
    name: "Knowledge Manager",
    description: "Captures decisions for institutional memory.",
  },
};

/** Pretty-case a slug-ish string: `foo_bar-baz` → `Foo bar baz`. */
export function prettyCase(input: string | undefined | null): string {
  if (!input) return "";
  const cleaned = String(input)
    .replace(/[_\-.]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!cleaned) return "";
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1).toLowerCase();
}

/**
 * Human-friendly display name for an agent_id.
 * Falls back to `prettyCase(agent_id)` if not in the table.
 */
export function displayName(agentId: string | undefined | null): string {
  if (!agentId) return "Helper";
  const hit = AGENT_DISPLAY[agentId];
  if (hit) return hit.name;
  return prettyCase(agentId) || "Helper";
}

/**
 * One-line description for an agent_id (suitable as a row subtitle or
 * tooltip).
 */
export function description(agentId: string | undefined | null): string {
  if (!agentId) return "";
  const hit = AGENT_DISPLAY[agentId];
  if (hit) return hit.description;
  return "";
}

// ── Lane labels ─────────────────────────────────────────────────────────────

/**
 * Human display for a lane. Accepts either:
 *   - the API integer (1 = auto, 2 = single sig, 3 = dual sig), OR
 *   - the prompt-tier string (`tier-2-auto`, `tier-1-spotcheck`,
 *     `tier-0-mandatory`).
 *
 * Per COPY_GUIDE.md §"Universal renames", the user-facing labels are:
 *   1 / tier-2-auto       → "Auto-handled"
 *   2 / tier-1-spotcheck  → "Needs your sign-off"
 *   3 / tier-0-mandatory  → "Needs two signatures"
 */
export function displayLane(lane: number | string | undefined | null): string {
  const n = laneAsNumber(lane);
  switch (n) {
    case 1:
      return "Auto-handled";
    case 2:
      return "Needs your sign-off";
    case 3:
      return "Needs two signatures";
    default:
      return "";
  }
}

/**
 * Short label for the segmented control / tab bar (single word/phrase).
 * Per COPY_GUIDE: "Auto" / "Yours" / "Two-signer".
 */
export function laneTabLabel(
  lane: number | string | undefined | null,
): string {
  const n = laneAsNumber(lane);
  switch (n) {
    case 1:
      return "Auto";
    case 2:
      return "Yours";
    case 3:
      return "Two-signer";
    default:
      return "";
  }
}

/** Coerce any lane representation we accept into the canonical 1|2|3 integer. */
export function laneAsNumber(
  lane: number | string | undefined | null,
): 1 | 2 | 3 | null {
  if (lane == null) return null;
  if (typeof lane === "number") {
    if (lane === 1 || lane === 2 || lane === 3) return lane;
    return null;
  }
  // String form — accept prompt-tier or already-stringified integer.
  const s = lane.toLowerCase();
  if (s === "tier-2-auto" || s === "1") return 1;
  if (s === "tier-1-spotcheck" || s === "2") return 2;
  if (s === "tier-0-mandatory" || s === "3") return 3;
  return null;
}

// ── Priority ────────────────────────────────────────────────────────────────

const PRIORITY_DISPLAY: Record<string, string> = {
  critical: "Critical",
  high: "High",
  normal: "Normal",
  low: "Low",
};

/**
 * Display label for a priority value. Capitalizes known values; falls back
 * to `prettyCase` for anything else.
 */
export function displayPriority(p: string | undefined | null): string {
  if (!p) return "Normal";
  const hit = PRIORITY_DISPLAY[p.toLowerCase()];
  if (hit) return hit;
  return prettyCase(p) || "Normal";
}

// ── Escalation tags ─────────────────────────────────────────────────────────

/**
 * Map known escalation / flag tags to plain English. Per COPY_GUIDE voice:
 * direct, no jargon, sentence case.
 */
const ESCALATION_DISPLAY: Record<string, string> = {
  // Cost / schedule / safety / equipment
  cost: "Cost impact",
  "cost-impact": "Cost impact",
  cost_impact: "Cost impact",
  schedule: "Schedule impact",
  "schedule-impact": "Schedule impact",
  schedule_impact: "Schedule impact",
  safety: "Safety flag",
  "safety-impact": "Safety flag",
  safety_impact: "Safety flag",
  "long-lead": "Long-lead equipment",
  long_lead: "Long-lead equipment",
  "critical-path": "Critical path risk",
  critical_path: "Critical path risk",
  // Trust / classification flags
  prompt_injection_detected: "Suspicious content",
  "prompt-injection-detected": "Suspicious content",
  prompt_injection: "Suspicious content",
  low_confidence: "Low confidence",
  "low-confidence": "Low confidence",
  ambiguous: "Ambiguous request",
  // Governance
  policy_violation: "Policy violation",
  "policy-violation": "Policy violation",
  needs_review: "Needs review",
  "needs-review": "Needs review",
  // Data hygiene
  missing_citation: "Missing citation",
  "missing-citation": "Missing citation",
  stale_source: "Source out of date",
  "stale-source": "Source out of date",
};

export function displayEscalation(tag: string | undefined | null): string {
  if (!tag) return "";
  const hit = ESCALATION_DISPLAY[tag.toLowerCase()];
  if (hit) return hit;
  return prettyCase(tag);
}

// ── Workflow ────────────────────────────────────────────────────────────────

/**
 * Map workflow IDs → plain-English action names.
 * Workflow IDs follow `<noun>.<verb>` (e.g. `rfi.classify`, `submittal.validate`).
 */
const WORKFLOW_DISPLAY: Record<string, string> = {
  "rfi.classify": "Sort RFI",
  "rfi.triage": "Sort RFI",
  "rfi.draft": "Draft RFI response",
  "rfi.respond": "Draft RFI response",
  "submittal.classify": "Sort submittal",
  "submittal.triage": "Sort submittal",
  "submittal.validate": "Check submittal",
  "submittal.spec_check": "Check submittal",
  "submittal.spec-check": "Check submittal",
  "procurement.watch": "Watch procurement",
  "procurement.alert": "Procurement alert",
  "dfr.summarize": "Summarize field report",
  "dfr.read": "Read field report",
  "safety.aggregate": "Roll up safety",
  "safety.summarize": "Summarize safety",
  "schedule.read": "Read schedule",
  "schedule.update": "Update schedule",
  "critical-path.watch": "Watch critical path",
  "critical_path.watch": "Watch critical path",
  "co.estimate": "Estimate change order",
  "change_order.estimate": "Estimate change order",
  "ccb.prep": "Prep change board",
  "owner.report": "Draft owner report",
  "owner_reporting.report": "Draft owner report",
  "status.update": "Write status update",
  "comms.draft": "Draft message",
  "knowledge.capture": "Capture decision",
  "daily_brief.compile": "Build daily brief",
  "daily-brief.compile": "Build daily brief",
};

/**
 * Display label for a workflow ID. Falls back to a pretty-cased version
 * (`rfi.classify` → "Rfi classify"; `foo_bar` → "Foo bar").
 */
export function displayWorkflow(w: string | undefined | null): string {
  if (!w) return "Item";
  const key = w.toLowerCase();
  const hit = WORKFLOW_DISPLAY[key];
  if (hit) return hit;
  // Light heuristic: split on dot and join with verb prefix.
  const parts = w.split(".");
  if (parts.length === 2) {
    const noun = prettyCase(parts[0]);
    const verb = prettyCase(parts[1]).toLowerCase();
    return `${verb.charAt(0).toUpperCase()}${verb.slice(1)} ${noun.toLowerCase()}`.trim();
  }
  return prettyCase(w) || "Item";
}

// ── Trust tier ──────────────────────────────────────────────────────────────

const TRUST_TIER_DISPLAY: Record<string, string> = {
  "tier-0": "Probation",
  tier_0: "Probation",
  "tier-1": "Standard",
  tier_1: "Standard",
  "tier-2": "Trusted",
  tier_2: "Trusted",
  probation: "Probation",
  standard: "Standard",
  trusted: "Trusted",
};

/**
 * Display label for a trust tier identifier.
 * Per COPY_GUIDE: Probation / Standard / Trusted.
 */
export function displayTrustTier(t: string | undefined | null): string {
  if (!t) return "";
  const hit = TRUST_TIER_DISPLAY[t.toLowerCase()];
  if (hit) return hit;
  return prettyCase(t);
}

// ── Confidence ──────────────────────────────────────────────────────────────

/**
 * Format a 0–1 confidence value as "X% confident" (per COPY_GUIDE
 * §"Universal renames"). Rounded to nearest integer.
 */
export function displayConfidence(
  c: number | undefined | null,
  withSuffix: boolean = true,
): string {
  if (c == null || Number.isNaN(c)) return "";
  const pct = Math.round(Math.max(0, Math.min(1, c)) * 100);
  return withSuffix ? `${pct}% confident` : `${pct}%`;
}
