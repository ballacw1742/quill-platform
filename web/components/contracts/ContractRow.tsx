"use client";

import * as React from "react";
import Link from "next/link";
import { FileText, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ContractListItem } from "@/lib/schemas";

// ── Helpers ───────────────────────────────────────────────────────────────
function relTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.round(diff / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatUSD(v: number | null | undefined): string {
  if (v == null) return "";
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${Math.round(v / 1_000)}K`;
  return `$${v}`;
}

function typeLabel(t: string | null | undefined): string {
  if (!t) return "";
  return t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// STATUS_TONE uses prod-existing design tokens: text-info/warning/success/danger
// per LOVABLE_PORT_CONTRACT.md known-token-equivalences.
const STATUS_TONE: Record<string, string> = {
  extracting: "bg-bg-elevated text-label-secondary",
  extracted: "bg-accent-tint text-info",
  reviewing: "bg-warning/15 text-warning",
  reviewed: "bg-success/15 text-success",
  drafting: "bg-accent/15 text-accent",
  drafted: "bg-accent/15 text-accent",
  failed: "bg-danger/15 text-danger",
};

// ── ContractRow ────────────────────────────────────────────────────────────
/**
 * ContractRow — Lovable-redesign card style.
 * Uses shadow-card (prod token), rounded-2xl card, warning/15 icon bg,
 * STATUS_TONE for the status badge (text-info/warning/success/danger),
 * and ChevronRight with value in flex-col right column.
 *
 * Navigation via Next.js <Link> (prod pattern) — no onClick prop needed.
 */
export function ContractRow({ contract }: { contract: ContractListItem }) {
  const title = contract.project_label || `Contract ${contract.upload_id.slice(0, 8)}`;
  const typeStr = typeLabel(contract.contract_type);
  const ago = contract.updated_at
    ? relTime(contract.updated_at)
    : contract.created_at
      ? relTime(contract.created_at)
      : "";
  const statusTone = STATUS_TONE[contract.status] ?? "bg-bg-elevated text-label-secondary";

  return (
    <Link
      href={`/contracts/${contract.upload_id}`}
      className="mb-2.5 flex w-full min-h-16 items-center gap-3 rounded-2xl bg-bg-elevated shadow-card p-5 text-left transition-transform active:scale-[0.98] no-tap-highlight"
    >
      {/* Icon */}
      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-warning/15 text-warning">
        <FileText className="h-6 w-6" />
      </div>

      {/* Text */}
      <div className="min-w-0 flex-1">
        <p className="truncate text-headline font-semibold text-label-primary">
          {title}
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          {typeStr && (
            <span className="text-footnote font-medium text-label-secondary">
              {typeStr}
            </span>
          )}
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-footnote font-semibold",
              statusTone,
            )}
          >
            {contract.status}
          </span>
          {ago && (
            <>
              <span className="text-footnote text-label-tertiary">·</span>
              <span className="text-footnote text-label-tertiary">{ago}</span>
            </>
          )}
        </div>
      </div>

      {/* Right: value + chevron */}
      <div className="flex flex-col items-end gap-1 shrink-0">
        {contract.total_value_usd != null && (
          <span className="text-subhead font-semibold text-label-primary tabular-nums">
            {formatUSD(contract.total_value_usd)}
          </span>
        )}
        <ChevronRight className="h-5 w-5 text-label-tertiary" />
      </div>
    </Link>
  );
}

export default ContractRow;
