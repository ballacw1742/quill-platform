"use client";

import * as React from "react";
import Link from "next/link";
import { Check } from "lucide-react";
import { formatAge } from "@/lib/today";
import type { ShippedItem } from "@/lib/today";

/**
 * RecentItemRow — a single row inside the "Recently shipped" section card.
 *
 * Shows a check icon, a past-tense status line, and a relative timestamp.
 * Touch target ≥ 44px.
 */

interface RecentItemRowProps {
  item: ShippedItem;
  now?: number;
}

export function RecentItemRow({ item, now = Date.now() }: RecentItemRowProps) {
  const age = formatAge(item.ts, now);

  const verb =
    item.kind === "approval"
      ? "Approved"
      : item.kind === "contract"
        ? "Drafted"
        : "Completed";

  return (
    <Link
      href={item.href}
      className="flex min-h-[52px] items-center gap-3 px-4 py-3 active:bg-bg-elevated/60 no-tap-highlight"
    >
      {/* Check icon */}
      <span
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-success/10 text-success"
        aria-hidden="true"
      >
        <Check className="h-3.5 w-3.5" />
      </span>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <p className="text-callout font-medium text-label-primary line-clamp-1">
          {verb} {item.label}
        </p>
        <p className="text-footnote text-label-tertiary">{age}</p>
      </div>
    </Link>
  );
}
