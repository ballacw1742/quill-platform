"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import type { ApprovalItem } from "@/lib/schemas";
import { formatAge } from "@/lib/today";
import { LANE_META } from "@/components/queue/laneMeta";

/**
 * NeedsSignoffRow — a single row inside the "Needs your sign-off" section card.
 *
 * Tapping opens the ApprovalDetailSheet (controlled externally via onOpen).
 * Touch target ≥ 44px.
 */

interface NeedsSignoffRowProps {
  item: ApprovalItem;
  onOpen: (id: string) => void;
  now?: number;
}

export function NeedsSignoffRow({
  item,
  onOpen,
  now = Date.now(),
}: NeedsSignoffRowProps) {
  const meta = LANE_META[item.lane];
  const title =
    item.summary ??
    (item.proposed_action?.payload as Record<string, string> | undefined)?.title ??
    item.workflow ??
    "Pending approval";
  const age = formatAge(item.created_at, now);

  // Lane chip colors per brief spec:
  // tier-0 → red, tier-1 → amber, tier-2 → grey
  const chipClass =
    item.lane === "tier-0-mandatory"
      ? "bg-danger/10 text-danger"
      : item.lane === "tier-1-spotcheck"
        ? "bg-warning/10 text-warning"
        : "bg-bg-elevated text-label-tertiary";

  return (
    <button
      type="button"
      onClick={() => onOpen(item.approval_id)}
      className="flex w-full min-h-[52px] items-center gap-3 px-4 py-3 text-left active:bg-bg-elevated/60 no-tap-highlight"
    >
      {/* Title + age */}
      <div className="flex-1 min-w-0">
        <p className="text-callout font-medium text-label-primary line-clamp-1">
          {title}
        </p>
        <p className="text-footnote text-label-tertiary">{age}</p>
      </div>

      {/* Lane chip */}
      <span
        className={cn(
          "shrink-0 rounded-full px-2 py-0.5 text-footnote font-medium",
          chipClass,
        )}
      >
        {meta?.short ?? item.lane}
      </span>
    </button>
  );
}
