import type { Lane } from "@/lib/schemas";

export const LANE_META: Record<
  Lane,
  { label: string; short: string; color: string; description: string; tone: string }
> = {
  "tier-0-mandatory": {
    label: "Lane 1 · Mandatory",
    short: "Mandatory",
    color: "bg-lane-tier0",
    tone: "text-lane-tier0",
    description: "Tier 0 — every item reviewed by Charles.",
  },
  "tier-1-spotcheck": {
    label: "Lane 2 · Spot-check",
    short: "Spot-check",
    color: "bg-lane-tier1",
    tone: "text-lane-tier1",
    description: "Tier 1 — sampled review; oldest first.",
  },
  "tier-2-auto": {
    label: "Lane 3 · Auto",
    short: "Auto",
    color: "bg-lane-tier2",
    tone: "text-lane-tier2",
    description: "Tier 2 — auto-execute; visible for awareness.",
  },
};

export const LANE_ORDER: Lane[] = ["tier-0-mandatory", "tier-1-spotcheck", "tier-2-auto"];

const PRIORITY_RANK: Record<string, number> = { critical: 0, high: 1, normal: 2, low: 3 };

export function sortItemsForLane<T extends { lane: Lane; created_at: string; priority?: string }>(
  items: T[],
  lane: Lane,
): T[] {
  const list = items.filter((i) => i.lane === lane);
  if (lane === "tier-1-spotcheck") {
    return list.sort((a, b) => +new Date(a.created_at) - +new Date(b.created_at));
  }
  if (lane === "tier-2-auto") {
    return list.sort(
      (a, b) =>
        (PRIORITY_RANK[a.priority ?? "normal"] ?? 2) - (PRIORITY_RANK[b.priority ?? "normal"] ?? 2) ||
        +new Date(a.created_at) - +new Date(b.created_at),
    );
  }
  // tier-0: priority first, then oldest
  return list.sort(
    (a, b) =>
      (PRIORITY_RANK[a.priority ?? "normal"] ?? 2) - (PRIORITY_RANK[b.priority ?? "normal"] ?? 2) ||
      +new Date(a.created_at) - +new Date(b.created_at),
  );
}
