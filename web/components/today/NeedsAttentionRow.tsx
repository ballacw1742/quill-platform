"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import type { ApprovalItem } from "@/lib/schemas";
import { formatStaleAge } from "@/lib/today";

/**
 * NeedsAttentionRow — a single row inside the "Needs attention" section card.
 *
 * Similar to NeedsSignoffRow but the lane chip is replaced by a stale-age
 * chip in amber/red to draw the eye. Touch target ≥ 44px.
 */

interface NeedsAttentionRowProps {
  item: ApprovalItem;
  onOpen: (id: string) => void;
  now?: number;
}

export function NeedsAttentionRow({
  item,
  onOpen,
  now = Date.now(),
}: NeedsAttentionRowProps) {
  const title =
    item.summary ??
    (item.proposed_action?.payload as Record<string, string> | undefined)?.title ??
    item.workflow ??
    "Pending approval";

  const staleAge = formatStaleAge(item.created_at, now);

  // Chip color scales with staleness: > 3 days → red, else amber
  const daysOld = Math.floor((now - +new Date(item.created_at)) / 86_400_000);
  const chipClass =
    daysOld >= 3
      ? "bg-danger/10 text-danger"
      : "bg-warning/10 text-warning";

  return (
    <button
      type="button"
      onClick={() => onOpen(item.approval_id)}
      className="flex w-full min-h-[52px] items-center gap-3 px-4 py-3 text-left active:bg-bg-elevated/60 no-tap-highlight"
    >
      {/* Title */}
      <div className="flex-1 min-w-0">
        <p className="text-callout font-medium text-label-primary line-clamp-1">
          {title}
        </p>
        <p className="text-footnote text-label-tertiary">Waiting for sign-off</p>
      </div>

      {/* Stale-age chip */}
      <span
        className={cn(
          "shrink-0 rounded-full px-2 py-0.5 text-footnote font-medium",
          chipClass,
        )}
      >
        {staleAge}
      </span>
    </button>
  );
}
