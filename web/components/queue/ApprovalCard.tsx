"use client";

import * as React from "react";
import Link from "next/link";
import { formatDistanceToNowStrict } from "date-fns";
import {
  AlertTriangle,
  ArrowUpRight,
  Cloud,
  CloudOff,
  Database,
  FileText,
  Flag,
  Workflow,
} from "lucide-react";
import { cn, truncate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import type { ApprovalItem } from "@/lib/schemas";
import { displayName, displayWorkflow } from "@/lib/agent-meta";

const TARGET_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  procore: Workflow,
  p6: Database,
  acc: FileText,
  drive: Cloud,
};

function targetIcon(t?: string | null) {
  if (!t) return CloudOff;
  return TARGET_ICON[t] ?? Cloud;
}

const PRIORITY_VARIANT: Record<string, "destructive" | "warning" | "secondary" | "muted"> = {
  critical: "destructive",
  high: "warning",
  normal: "secondary",
  low: "muted",
};

export function ApprovalCard({ item }: { item: ApprovalItem }) {
  const TargetIcon = targetIcon(item.proposed_action.target_system ?? null);
  const age = formatDistanceToNowStrict(new Date(item.created_at), { addSuffix: false });
  const priority = item.priority ?? "normal";
  const summary =
    item.summary ??
    item.rationale ??
    `${item.proposed_action.kind} → ${item.proposed_action.target_system ?? "draft-only"}`;

  return (
    <Link
      href={`/approvals/${item.approval_id}`}
      className={cn(
        "group block rounded-md border bg-card p-3 transition-colors hover:border-primary/40 hover:bg-accent/30",
        "animate-fade-in",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <Badge variant="outline" className="text-[10px]">
            {displayName(item.agent_id)}
          </Badge>
          <span className="truncate text-xs text-muted-foreground">
            {displayWorkflow(item.workflow)}
          </span>
        </div>
        <ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
      </div>

      <p className="mt-1.5 line-clamp-2 text-sm font-medium leading-snug">
        {truncate(summary, 100)}
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
        <Badge variant={PRIORITY_VARIANT[priority]} className="capitalize">
          {priority === "critical" || priority === "high" ? (
            <Flag className="mr-1 h-3 w-3" />
          ) : null}
          {priority}
        </Badge>
        <span className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-muted-foreground">
          <TargetIcon className="h-3 w-3" />
          {item.proposed_action.target_system ?? "draft-only"}
        </span>
        <span className="inline-flex items-center gap-1 text-muted-foreground" title={item.created_at}>
          {age} old
        </span>
        <span
          className={cn(
            "ml-auto inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-[10px]",
            item.confidence < 0.7
              ? "bg-destructive/10 text-destructive"
              : item.confidence < 0.85
                ? "bg-warning/10 text-warning"
                : "bg-success/10 text-success",
          )}
        >
          {(item.confidence * 100).toFixed(0)}%
        </span>
      </div>

      {item.escalations && item.escalations.length > 0 && (
        <div className="mt-2 flex items-center gap-1 text-[11px] text-warning">
          <AlertTriangle className="h-3 w-3" />
          {item.escalations.join(" · ")}
        </div>
      )}
    </Link>
  );
}
