/**
 * queue-categories.ts — workflow-to-display-label mapping and grouping logic
 * for the Queue page category view.
 *
 * Pure functions; no React/DOM deps — safe for vitest node environment.
 *
 * localStorage strategy (documented choice):
 *   Force-expand a category if it has ANY pending items, regardless of stored
 *   state. This ensures no new work is ever hidden. Collapsed, all-decided
 *   categories keep their stored state. A "Reset" affordance can be added
 *   later if the force-expand ever gets annoying.
 *   (Simpler alternative to diffing new-vs-prior pending items.)
 */

import type { ApprovalItem, Lane } from "./schemas";

// ── Workflow → display label ─────────────────────────────────────────────────

const EXACT_MAP: Record<string, string> = {
  "aace_classification.publish": "AACE Classifications",
  "cost_schedule_package.publish": "Cost & Schedule Packages",
};

/**
 * Prefix rules — evaluated in order. First match wins.
 * All `rfi.*` variants map to "RFIs", all `submittal.*` to "Submittals", etc.
 */
const PREFIX_MAP: Array<[prefix: string, label: string]> = [
  ["rfi.", "RFIs"],
  ["submittal.", "Submittals"],
  ["dfr.", "Daily Field Reports"],
  ["po.", "Purchase Orders"],
];

/**
 * Map a workflow value to its display label.
 * Precedence: exact match → prefix match → prettified fallback.
 *
 * @example
 *   workflowToLabel("rfi.draft")            // "RFIs"
 *   workflowToLabel("aace_classification.publish") // "AACE Classifications"
 *   workflowToLabel("custom.thing")         // "Custom Thing"
 */
export function workflowToLabel(workflow: string | undefined | null): string {
  if (!workflow) return "Other";
  if (EXACT_MAP[workflow]) return EXACT_MAP[workflow];
  for (const [prefix, label] of PREFIX_MAP) {
    if (workflow.startsWith(prefix)) return label;
  }
  // Prettify: replace dots/underscores with spaces, title-case each word.
  return workflow
    .replace(/[._]+/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

// ── Grouping and sorting ─────────────────────────────────────────────────────

/**
 * Lane priority for within-category sort.
 * Lower number = displayed first (dual-sig is most urgent).
 */
const LANE_SORT_ORDER: Record<Lane, number> = {
  "tier-0-mandatory": 0,
  "tier-1-spotcheck": 1,
  "tier-2-auto": 2,
};

export type QueueCategory = {
  label: string;
  items: ApprovalItem[];
  /** Total number of items with status === "pending". */
  pendingCount: number;
  /** true if pendingCount > 0. */
  hasPending: boolean;
};

/**
 * Group and sort a flat list of items into display categories.
 *
 * Sort within categories:
 *   1. Lane priority (tier-0-mandatory first)
 *   2. Most recently created first
 *
 * Sort of categories:
 *   1. Categories with pending items first
 *   2. Then alphabetical by display label
 *
 * Empty categories are never returned (all categories have ≥ 1 item by
 * construction — hide-on-empty is handled by the caller filtering the result).
 */
export function groupItemsByCategory(items: ApprovalItem[]): QueueCategory[] {
  // Accumulate items per label.
  const map = new Map<string, ApprovalItem[]>();
  for (const item of items) {
    const label = workflowToLabel(item.workflow);
    const bucket = map.get(label);
    if (bucket) {
      bucket.push(item);
    } else {
      map.set(label, [item]);
    }
  }

  // Build category objects with sorted items.
  const categories: QueueCategory[] = Array.from(map.entries()).map(
    ([label, catItems]) => {
      const sorted = [...catItems].sort((a, b) => {
        const laneA = LANE_SORT_ORDER[a.lane] ?? 1;
        const laneB = LANE_SORT_ORDER[b.lane] ?? 1;
        if (laneA !== laneB) return laneA - laneB;
        // Most recently created first (descending date).
        return +new Date(b.created_at) - +new Date(a.created_at);
      });
      const pendingCount = catItems.filter((i) => i.status === "pending").length;
      return {
        label,
        items: sorted,
        pendingCount,
        hasPending: pendingCount > 0,
      };
    },
  );

  // Sort categories: pending-first, then label A-Z.
  categories.sort((a, b) => {
    if (a.hasPending !== b.hasPending) return a.hasPending ? -1 : 1;
    return a.label.localeCompare(b.label);
  });

  return categories;
}

// ── localStorage persistence ─────────────────────────────────────────────────

const LS_KEY = "quill.queue.expandedCategories.v1";

/**
 * Load expanded category labels from localStorage.
 * Returns null if localStorage is unavailable or the value is invalid.
 */
export function loadExpandedCategories(): string[] | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(LS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.every((s) => typeof s === "string")) {
      return parsed as string[];
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Persist the current set of expanded category labels to localStorage.
 */
export function saveExpandedCategories(expanded: string[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(LS_KEY, JSON.stringify(expanded));
  } catch {
    // Storage full or private browsing — silently ignore.
  }
}

/**
 * Compute the initial set of expanded category labels.
 *
 * Rules:
 *   - A category is expanded if it has ANY pending items (regardless of
 *     stored state). New work must never be hidden.
 *   - Otherwise, if the user previously had the category expanded (stored),
 *     respect that preference.
 *   - Otherwise, default to collapsed.
 *
 * @param categories  The current set of categories.
 * @param stored      Labels from localStorage; null means no stored state.
 */
export function computeInitialExpansion(
  categories: QueueCategory[],
  stored: string[] | null,
): Set<string> {
  const expanded = new Set<string>();
  for (const cat of categories) {
    if (cat.hasPending) {
      // Always expand when there is pending work.
      expanded.add(cat.label);
    } else if (stored !== null && stored.includes(cat.label)) {
      // No pending items — respect the stored user preference.
      expanded.add(cat.label);
    }
  }
  return expanded;
}

// ── API error classification (used by useDecide and tests) ───────────────────

/**
 * Classify a decide-mutation error into a toast variant.
 *
 * The `ApiError` class (from api.ts) attaches `status: number` to thrown
 * errors. This helper is a pure function so it can be unit-tested without
 * mocking the full React Query stack.
 */
export type DecideErrorKind = "already-decided" | "auth-required" | "unknown";

export function classifyDecideError(e: unknown): DecideErrorKind {
  if (e != null && typeof e === "object" && "status" in e) {
    const status = (e as { status: unknown }).status;
    if (status === 409) return "already-decided";
    if (status === 401) return "auth-required";
  }
  return "unknown";
}
