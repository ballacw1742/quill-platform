"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import type { ApprovalItem } from "@/lib/schemas";

/**
 * Inline flag chips for the queue list row, per DESIGN_SYSTEM §2 status
 * mapping + MOBILE_UX_SPEC §1 row pattern.
 *
 * Examples (small caps caption-1):
 *   ⚠ critical · $ cost · ⏱ schedule
 *
 * Source: derived from item.escalations + priority.
 */

type Flag = {
  key: string;
  /** Plain-English label per COPY_GUIDE §"Detail screen rewrites". */
  label: string;
  /** Visual tone tier. */
  tone: "danger" | "warning" | "info";
  /** Single emoji per COPY_GUIDE: 💲 ⏱ ⚠ ⏳ */
  emoji: string;
};

function detectFlags(item: ApprovalItem): Flag[] {
  const flags: Flag[] = [];
  const esc = item.escalations ?? [];
  const escSet = new Set(esc.map((e) => e.toLowerCase()));

  if (
    escSet.has("safety") ||
    escSet.has("safety-impact") ||
    escSet.has("safety_impact") ||
    item.priority === "critical"
  ) {
    flags.push({
      key: "safety",
      label: "Safety flag",
      tone: "danger",
      emoji: "⚠",
    });
  }
  if (escSet.has("critical-path") || escSet.has("critical_path")) {
    flags.push({
      key: "cp",
      label: "Critical path risk",
      tone: "danger",
      emoji: "⚠",
    });
  }
  if (
    escSet.has("cost") ||
    escSet.has("cost-impact") ||
    escSet.has("cost_impact")
  ) {
    flags.push({
      key: "cost",
      label: "Cost impact",
      tone: "warning",
      emoji: "💲",
    });
  }
  if (
    escSet.has("schedule") ||
    escSet.has("schedule-impact") ||
    escSet.has("schedule_impact")
  ) {
    flags.push({
      key: "sched",
      label: "Schedule impact",
      tone: "warning",
      emoji: "⏱",
    });
  }
  if (escSet.has("long-lead") || escSet.has("long_lead")) {
    flags.push({
      key: "long-lead",
      label: "Long-lead equipment",
      tone: "warning",
      emoji: "⏳",
    });
  }
  return flags;
}

const TONE_CLASS: Record<Flag["tone"], string> = {
  danger: "bg-danger/10 text-danger",
  warning: "bg-warning/10 text-warning",
  info: "bg-info/10 text-info",
};

export function FlagChips({
  item,
  className,
}: {
  item: ApprovalItem;
  className?: string;
}) {
  const flags = detectFlags(item);
  if (flags.length === 0) return null;
  return (
    <div className={cn("flex flex-wrap items-center gap-1", className)}>
      {flags.map((f) => (
        <span
          key={f.key}
          className={cn(
            "inline-flex items-center gap-1 rounded-sm px-1.5 py-[2px] text-caption-1",
            TONE_CLASS[f.tone],
          )}
        >
          <span aria-hidden="true">{f.emoji}</span>
          <span>{f.label}</span>
        </span>
      ))}
    </div>
  );
}

export { detectFlags };
