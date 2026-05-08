import type { Lane } from "@/lib/schemas";
import { displayLane, laneTabLabel } from "@/lib/agent-meta";

/**
 * UI metadata per lane. Note the storage keys remain the prompt-tier
 * identifiers (`tier-0-mandatory` etc.) — those are the wire-format
 * values the API uses. The user-facing labels come from `lib/agent-meta`.
 *
 * Lane mapping (per COPY_GUIDE §"Universal renames"):
 *   tier-2-auto       (lane 1) → "Auto-handled"        ("Auto"      tab)
 *   tier-1-spotcheck  (lane 2) → "Needs your sign-off" ("Yours"     tab)
 *   tier-0-mandatory  (lane 3) → "Needs two signatures" ("Two-signer" tab)
 */
export const LANE_META: Record<
  Lane,
  {
    /** Long label, e.g. "Needs your sign-off". */
    label: string;
    /** Short tab/segmented-control label, e.g. "Yours". */
    short: string;
    /** Same as `label`, kept for any caller that wants a friendlier alias. */
    display: string;
    /** Tailwind background class for any lane-tinted chip. */
    color: string;
    /** Tailwind text class. */
    tone: string;
    /** One-sentence subtitle explaining the lane. */
    description: string;
  }
> = {
  "tier-0-mandatory": {
    label: displayLane("tier-0-mandatory"), // "Needs two signatures"
    short: laneTabLabel("tier-0-mandatory"), // "Two-signer"
    display: displayLane("tier-0-mandatory"),
    color: "bg-lane-tier0",
    tone: "text-lane-tier0",
    description:
      "Big-impact items — usually money or schedule changes — that need both you and a partner.",
  },
  "tier-1-spotcheck": {
    label: displayLane("tier-1-spotcheck"), // "Needs your sign-off"
    short: laneTabLabel("tier-1-spotcheck"), // "Yours"
    display: displayLane("tier-1-spotcheck"),
    color: "bg-lane-tier1",
    tone: "text-lane-tier1",
    description: "Items that need your sign-off only.",
  },
  "tier-2-auto": {
    label: displayLane("tier-2-auto"), // "Auto-handled"
    short: laneTabLabel("tier-2-auto"), // "Auto"
    display: displayLane("tier-2-auto"),
    color: "bg-lane-tier2",
    tone: "text-lane-tier2",
    description:
      "Routine items the system handled automatically — review any time.",
  },
};

export const LANE_ORDER: Lane[] = [
  "tier-0-mandatory",
  "tier-1-spotcheck",
  "tier-2-auto",
];

const PRIORITY_RANK: Record<string, number> = {
  critical: 0,
  high: 1,
  normal: 2,
  low: 3,
};

export function sortItemsForLane<
  T extends { lane: Lane; created_at: string; priority?: string },
>(items: T[], lane: Lane): T[] {
  const list = items.filter((i) => i.lane === lane);
  if (lane === "tier-1-spotcheck") {
    return list.sort(
      (a, b) => +new Date(a.created_at) - +new Date(b.created_at),
    );
  }
  if (lane === "tier-2-auto") {
    return list.sort(
      (a, b) =>
        (PRIORITY_RANK[a.priority ?? "normal"] ?? 2) -
          (PRIORITY_RANK[b.priority ?? "normal"] ?? 2) ||
        +new Date(a.created_at) - +new Date(b.created_at),
    );
  }
  // tier-0: priority first, then oldest
  return list.sort(
    (a, b) =>
      (PRIORITY_RANK[a.priority ?? "normal"] ?? 2) -
        (PRIORITY_RANK[b.priority ?? "normal"] ?? 2) ||
      +new Date(a.created_at) - +new Date(b.created_at),
  );
}
