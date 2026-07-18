"use client";

/**
 * DealCard -- Lovable redesign visual port.
 * Ported from: quill-platform-builder/src/components/quill/pipeline/DealCard.tsx
 * Token mapping: shadow-sm -> shadow-card; text-green-400 -> text-success;
 *   text-yellow-400 -> text-warning; bg-bg-elevated (badge) -> bg-fill-quaternary.
 */

import { cn } from "@/lib/utils";
import type { Deal } from "@/lib/schemas";

function formatValue(v: number | null | undefined): string {
  if (v == null) return "--";
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
  return `$${v.toFixed(0)}`;
}

function formatMW(v: number | null | undefined): string {
  if (v == null) return "";
  return `${v.toFixed(0)} MW`;
}

function probColor(pct: number | null | undefined): string {
  if (pct == null) return "text-label-tertiary bg-fill-quaternary";
  if (pct >= 70) return "text-success bg-success/10";
  if (pct >= 40) return "text-warning bg-warning/10";
  return "text-label-tertiary bg-fill-quaternary";
}

function isOverdue(dateStr: string | null | undefined): boolean {
  if (!dateStr) return false;
  return new Date(dateStr) < new Date();
}

export function DealCard({
  deal,
  accountName,
  onClick,
  onViewCustomer,
}: {
  deal: Deal;
  accountName?: string;
  onClick: () => void;
  onViewCustomer?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full min-h-16 text-left rounded-2xl p-4 mb-2.5",
        "bg-bg-elevated shadow-card",
        "transition-transform active:scale-[0.98] no-tap-highlight",
      )}
    >
      {accountName && (
        <p className="text-headline font-semibold text-label-primary truncate">
          {accountName}
        </p>
      )}
      <p className="text-footnote text-label-secondary truncate mt-0.5">{deal.name}</p>

      <div className="flex items-center flex-wrap gap-1.5 mt-2.5">
        {deal.mw_required != null && (
          <span className="text-footnote font-semibold text-accent bg-accent/10 rounded-full px-2 py-0.5">
            {formatMW(deal.mw_required)}
          </span>
        )}
        {deal.value_usd != null && (
          <span className="text-footnote font-medium text-label-secondary tabular-nums">
            {formatValue(deal.value_usd)}
          </span>
        )}
        {deal.probability_pct != null && (
          <span
            className={cn(
              "text-footnote font-semibold rounded-full px-2 py-0.5",
              probColor(deal.probability_pct),
            )}
          >
            {deal.probability_pct}%
          </span>
        )}
        {deal.expected_close && (
          <span
            className={cn(
              "text-footnote rounded-full px-2 py-0.5",
              isOverdue(deal.expected_close)
                ? "text-danger bg-danger/10 font-semibold"
                : "text-label-tertiary",
            )}
          >
            {deal.expected_close}
          </span>
        )}
      </div>

      {deal.stage === "won" && onViewCustomer && (
        <span
          role="link"
          tabIndex={0}
          onClick={(e) => {
            e.stopPropagation();
            onViewCustomer();
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.stopPropagation();
              e.preventDefault();
              onViewCustomer();
            }
          }}
          className="mt-2 inline-block text-footnote font-semibold text-accent hover:underline cursor-pointer"
        >
          View Customer
        </span>
      )}
    </button>
  );
}
