"use client";

/**
 * CustomerCard — iOS-style card for the Customers module list.
 *
 * Ported from Lovable: quill-platform-builder/src/components/quill/customers/CustomerCard.tsx
 * Token mappings (contract §Known token equivalences):
 *   bg-bg-elevated shadow-card  (Lovable) → kept as-is (exist in prod)
 *   bg-chrome-solid             (Lovable) → bg-bg-elevated border border-hairline (contract rule)
 *   text-success / text-warning / text-danger → kept (exist in prod)
 *   bg-fill-tertiary            (Lovable) → bg-separator/30
 *   bg-fill-quaternary          (Lovable) → bg-chrome/60
 * No inline hex. No emojis.
 */

import * as React from "react";
import { ChevronRight, Ticket } from "lucide-react";
import { cn } from "@/lib/utils";
import type { CustomerDetail } from "@/lib/schemas";

export function healthColor(score: number | null | undefined): string {
  if (score == null) return "text-label-secondary";
  if (score >= 80) return "text-success";
  if (score >= 60) return "text-warning";
  return "text-danger";
}

export function healthBarColor(score: number | null | undefined): string {
  if (score == null) return "bg-separator/30";
  if (score >= 80) return "bg-success";
  if (score >= 60) return "bg-warning";
  return "bg-danger";
}

function ticketBadgeCls(count: number, hasCritical: boolean): string {
  if (count === 0) return "text-label-tertiary bg-chrome/60";
  if (hasCritical) return "text-danger bg-danger/10";
  return "text-warning bg-warning/10";
}

export function CustomerCard({
  customer,
  onClick,
}: {
  customer: CustomerDetail;
  onClick: () => void;
}) {
  const score = customer.health?.total ?? null;
  const hasCritical =
    (customer.health?.open_p1 ?? 0) > 0 || (customer.health?.open_p2 ?? 0) > 0;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full min-h-16 text-left rounded-2xl p-5 mb-2.5",
        "bg-bg-elevated shadow-card",
        "transition-transform active:scale-[0.98] no-tap-highlight",
      )}
    >
      {/* Account name row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <p className="text-title-3 font-semibold text-label-primary truncate">
            {customer.name}
          </p>
          {customer.industry && (
            <p className="text-subhead text-label-secondary truncate mt-1">
              {customer.industry}
            </p>
          )}
          {customer.primary_contact_name && (
            <p className="text-footnote text-label-tertiary truncate mt-0.5">
              {customer.primary_contact_name}
            </p>
          )}
        </div>
        <ChevronRight className="w-5 h-5 text-label-tertiary flex-shrink-0 mt-1" />
      </div>

      {/* Health score bar */}
      <div className="mt-4">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-footnote font-medium text-label-tertiary">Health</span>
          <span className={cn("text-subhead font-bold tabular-nums", healthColor(score))}>
            {score != null ? `${score}` : "—"}
          </span>
        </div>
        {/* bg-chrome-solid → bg-bg-elevated border border-hairline per contract */}
        <div className="h-2 rounded-full bg-bg-elevated border border-hairline overflow-hidden">
          <div
            className={cn("h-full rounded-full transition-all", healthBarColor(score))}
            style={{ width: `${score ?? 0}%` }}
          />
        </div>
      </div>

      {/* Badges row */}
      <div className="flex items-center flex-wrap gap-2 mt-3">
        <span
          className={cn(
            "flex items-center gap-1 text-footnote font-semibold rounded-full px-2.5 py-0.5",
            ticketBadgeCls(customer.open_ticket_count, hasCritical),
          )}
        >
          <Ticket className="w-3.5 h-3.5" />
          {customer.open_ticket_count} open
        </span>
        {customer.campus_id && (
          <span className="text-footnote font-semibold text-accent bg-accent/10 rounded-full px-2.5 py-0.5">
            Campus linked
          </span>
        )}
        {customer.type === "prospect" && (
          <span className="text-footnote font-semibold text-label-secondary bg-bg-elevated border border-hairline rounded-full px-2.5 py-0.5">
            Prospect
          </span>
        )}
      </div>
    </button>
  );
}
