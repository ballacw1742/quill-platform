"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Content-shaped skeleton primitives.
 *
 * Per DESIGN_SYSTEM.md §"Loading states":
 *   - Skeleton rows with shimmer animation (1.4 s loop, opacity 0.4 → 0.7).
 *   - **No "Loading..." text strings.** Show the skeleton, that's it.
 *   - Skeletons should mirror the actual content shape (icon + N text
 *     lines + chip), so the page doesn't shift on first paint.
 *
 * The shimmer animation lives in tailwind.config (`animate-shimmer`); these
 * primitives just compose the right rectangles over `bg-bg-elevated`.
 */

/** Atomic shimmer rectangle. Always renders on `bg-bg-elevated` so it's visible
 * against `bg-bg-tertiary` cards and `bg-bg` page backgrounds. Pass `tone="dark"`
 * to pull the rectangle one shade darker on already-elevated surfaces. */
export function SkelBar({
  className,
  tone = "default",
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { tone?: "default" | "dark" }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "block rounded-sm animate-shimmer",
        tone === "dark" ? "bg-bg-tertiary" : "bg-bg-elevated",
        className,
      )}
      {...props}
    />
  );
}

/** Standard ListRow-shaped skeleton: 28 px icon + 2 text lines + chip. */
export function SkelListRow({ tone = "default" }: { tone?: "default" | "dark" }) {
  return (
    <div
      className="flex items-center gap-3 px-4 py-3 min-h-[56px]"
      aria-hidden="true"
    >
      <SkelBar tone={tone} className="h-7 w-7 shrink-0 rounded-md" />
      <div className="flex-1 space-y-1.5">
        <SkelBar tone={tone} className="h-3.5 w-2/3" />
        <SkelBar tone={tone} className="h-3 w-5/6" />
      </div>
      <SkelBar tone={tone} className="h-3 w-10 shrink-0" />
    </div>
  );
}

/** A list of N SkelListRow inside a tertiary card surface. */
export function SkelList({
  count = 6,
  ariaLabel,
  tone = "default",
  className,
}: {
  count?: number;
  ariaLabel: string;
  tone?: "default" | "dark";
  className?: string;
}) {
  return (
    <ul
      className={cn(
        "divide-y divide-separator/40 bg-bg-tertiary",
        className,
      )}
      role="status"
      aria-label={ariaLabel}
      aria-busy="true"
    >
      {Array.from({ length: count }).map((_, i) => (
        <li key={i}>
          <SkelListRow tone={tone} />
        </li>
      ))}
      <span className="sr-only">{ariaLabel}</span>
    </ul>
  );
}

/** Card-shaped skeleton: rounded-xl on tertiary surface with title + 2 lines. */
export function SkelCard({
  className,
  rows = 2,
}: {
  className?: string;
  rows?: number;
}) {
  return (
    <section
      className={cn(
        "overflow-hidden rounded-xl bg-bg-tertiary p-4 shadow-card",
        className,
      )}
      aria-hidden="true"
    >
      <div className="space-y-2">
        <SkelBar className="h-4 w-1/3" />
        {Array.from({ length: rows }).map((_, i) => (
          <SkelBar key={i} className="h-3.5 w-full last:w-5/6" />
        ))}
      </div>
    </section>
  );
}

/** Section-card-shaped skeleton matching the /today section card layout:
 * icon + title + subtitle + chip. */
export function SkelSectionCard() {
  return (
    <div
      className="overflow-hidden rounded-xl bg-bg-tertiary shadow-card"
      aria-hidden="true"
    >
      <div className="flex items-center gap-3 px-4 py-4 min-h-[68px]">
        <SkelBar className="h-7 w-7 shrink-0 rounded-md" />
        <div className="flex-1 space-y-1.5">
          <SkelBar className="h-4 w-1/3" />
          <SkelBar className="h-3.5 w-2/3" />
        </div>
        <SkelBar className="h-3.5 w-14 shrink-0" />
      </div>
    </div>
  );
}

/** Hero-card-shaped skeleton matching /today's "Top of mind" layout:
 * sparkle row + 3 short stacked items. */
export function SkelHeroCard() {
  return (
    <section
      className="overflow-hidden rounded-xl bg-bg-tertiary p-4 shadow-card space-y-3"
      aria-hidden="true"
    >
      <div className="flex items-center gap-2">
        <SkelBar className="h-4 w-4 rounded-sm" />
        <SkelBar className="h-4 w-24" />
      </div>
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="space-y-1">
          <SkelBar className="h-3.5 w-2/3" />
          <SkelBar className="h-3 w-full" />
        </div>
      ))}
    </section>
  );
}
