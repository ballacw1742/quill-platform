"use client";

import * as React from "react";
import {
  AlertTriangle,
  Clock,
  DollarSign,
  ShieldAlert,
  type LucideIcon,
} from "lucide-react";
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
  label: string;
  tone: "danger" | "warning" | "info";
  icon: LucideIcon;
};

function detectFlags(item: ApprovalItem): Flag[] {
  const flags: Flag[] = [];
  const esc = item.escalations ?? [];
  const escSet = new Set(esc.map((e) => e.toLowerCase()));

  if (
    escSet.has("safety") ||
    escSet.has("safety-impact") ||
    item.priority === "critical"
  ) {
    flags.push({
      key: "safety",
      label: "safety",
      tone: "danger",
      icon: ShieldAlert,
    });
  }
  if (escSet.has("critical-path") || escSet.has("critical_path")) {
    flags.push({
      key: "cp",
      label: "critical path",
      tone: "danger",
      icon: AlertTriangle,
    });
  }
  if (
    escSet.has("cost") ||
    escSet.has("cost-impact") ||
    escSet.has("cost_impact")
  ) {
    flags.push({
      key: "cost",
      label: "cost",
      tone: "warning",
      icon: DollarSign,
    });
  }
  if (
    escSet.has("schedule") ||
    escSet.has("schedule-impact") ||
    escSet.has("long-lead")
  ) {
    flags.push({
      key: "sched",
      label: "schedule",
      tone: "warning",
      icon: Clock,
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
      {flags.map((f) => {
        const Icon = f.icon;
        return (
          <span
            key={f.key}
            className={cn(
              "inline-flex items-center gap-1 rounded-sm px-1.5 py-[2px] text-caption-1 uppercase tracking-wider",
              TONE_CLASS[f.tone],
            )}
          >
            <Icon className="h-3 w-3" aria-hidden="true" />
            {f.label}
          </span>
        );
      })}
    </div>
  );
}

export { detectFlags };
