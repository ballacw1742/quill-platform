"use client";

import * as React from "react";
import { formatDistanceToNowStrict } from "date-fns";
import { Check, ExternalLink, X } from "lucide-react";
import type { ApprovalItem } from "@/lib/schemas";
import { ListRow } from "@/components/ui/list-row";
import { SwipeRow, type SwipeAction } from "@/components/ui/swipe-row";
import { AgentBadge } from "./AgentBadge";
import { FlagChips, detectFlags } from "./FlagChips";
import { truncate } from "@/lib/utils";

/**
 * A single row in the /queue list, per MOBILE_UX_SPEC §"Tab 1 — Queue".
 *
 * - Tap → opens detail sheet (caller-supplied onOpen handler).
 * - Swipe-left → trailing actions (Approve / Reject) — Lane 2 only, and only
 *   when no critical / safety flag is present (DESIGN_SYSTEM §7 swipe rules).
 * - Swipe-right → leading "Open" action (parity with tap, just a thumb-friendly
 *   alternative).
 */
export function ApprovalRow({
  item,
  onOpen,
  onApprove,
  onReject,
}: {
  item: ApprovalItem;
  onOpen: (id: string) => void;
  /** Optional fast-approve handler (Lane 2 swipe). */
  onApprove?: (id: string) => void;
  /** Optional fast-reject handler (Lane 2 swipe). */
  onReject?: (id: string) => void;
}) {
  const age = formatDistanceToNowStrict(new Date(item.created_at), {
    addSuffix: false,
  });
  const summary =
    item.summary ??
    item.rationale ??
    `${item.proposed_action.kind} → ${item.proposed_action.target_system ?? "draft-only"}`;

  const flags = detectFlags(item);
  const hasCriticalFlag = flags.some((f) => f.tone === "danger");
  // Swipe is enabled only on Lane 2 (single-sig) and only when not critical-flagged.
  const swipeEnabled =
    !!onApprove &&
    !!onReject &&
    item.lane === "tier-1-spotcheck" &&
    !hasCriticalFlag;

  const trailing: SwipeAction[] = swipeEnabled
    ? [
        {
          key: "reject",
          label: "Reject",
          tone: "danger",
          icon: <X className="h-5 w-5" />,
          onAction: () => onReject!(item.approval_id),
        },
        {
          key: "approve",
          label: "Approve",
          tone: "success",
          icon: <Check className="h-5 w-5" />,
          onAction: () => onApprove!(item.approval_id),
          primary: true,
        },
      ]
    : [];
  const leading: SwipeAction[] = [
    {
      key: "open",
      label: "Open",
      tone: "accent",
      icon: <ExternalLink className="h-5 w-5" />,
      onAction: () => onOpen(item.approval_id),
      primary: true,
    },
  ];

  // Title: prefer the workflow + key reference if recognizable from payload.
  const title = humanTitle(item);

  // Right-side chip = age (e.g. "2h").
  const chip = age;

  // Determine accent stripe (left) for visibility of high-priority items.
  const accent = hasCriticalFlag
    ? "danger"
    : flags.some((f) => f.tone === "warning")
      ? "warning"
      : undefined;

  return (
    <SwipeRow leading={leading} trailing={trailing} enabled={swipeEnabled || leading.length > 0}>
      <ListRow
        icon={<AgentBadge agentId={item.agent_id} />}
        iconTone="neutral"
        title={truncate(title, 64)}
        subtitle={summary}
        chip={chip}
        chevron={false}
        accent={accent}
        onClick={() => onOpen(item.approval_id)}
        ariaLabel={`Open approval ${item.approval_id}`}
        footer={flags.length > 0 ? <FlagChips item={item} /> : undefined}
      />
    </SwipeRow>
  );
}

function humanTitle(item: ApprovalItem): string {
  // Heuristic: if payload has a recognizable id, use "<workflow> · <id>"
  const p = item.proposed_action.payload as Record<string, unknown>;
  const candidates = [
    "rfi_id",
    "rfi",
    "submittal_id",
    "po_id",
    "drawing_id",
    "id",
    "ref",
  ];
  for (const k of candidates) {
    const v = p?.[k];
    if (typeof v === "string" && v.length < 64) {
      return `${prettyWorkflow(item.workflow)} · ${v}`;
    }
  }
  return prettyWorkflow(item.workflow);
}

function prettyWorkflow(w: string): string {
  if (!w) return "Approval";
  return w
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
