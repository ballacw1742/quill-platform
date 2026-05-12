"use client";

import * as React from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { formatAge } from "@/lib/today";
import type { InFlightItem } from "@/lib/today";

/**
 * InFlightRow — a single row inside the "In-flight work" section card.
 *
 * Shows a spinning loader icon, a descriptive status line, and links to
 * the item's detail page. Touch target ≥ 44px.
 */

interface InFlightRowProps {
  item: InFlightItem;
  now?: number;
}

const STATUS_VERB: Record<string, string> = {
  drafting: "Drafting",
  reviewing: "Reviewing",
  extracting: "Extracting",
  classifying: "Classifying",
  estimating: "Estimating",
  queued: "Queued",
  uploaded: "Uploading",
};

export function InFlightRow({ item, now = Date.now() }: InFlightRowProps) {
  const verb = STATUS_VERB[item.status] ?? "Processing";
  const kindLabel = item.kind === "contract" ? "subcontract" : "estimate";
  const age = formatAge(item.started_at, now);

  return (
    <Link
      href={item.href}
      className="flex min-h-[52px] items-center gap-3 px-4 py-3 active:bg-bg-elevated/60 no-tap-highlight"
    >
      {/* Spinning loader */}
      <Loader2
        className="h-4 w-4 shrink-0 animate-spin text-accent"
        aria-hidden="true"
      />

      {/* Status line */}
      <div className="flex-1 min-w-0">
        <p className="text-callout font-medium text-label-primary line-clamp-1">
          {item.label}
        </p>
        <p className="text-footnote text-label-tertiary">
          {verb} · {kindLabel} · {age}
        </p>
      </div>
    </Link>
  );
}
