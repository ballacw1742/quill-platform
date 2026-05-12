"use client";

import * as React from "react";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * SectionCard — container card for a Today page section.
 *
 * Renders a rounded, elevated card with:
 *   - A header row: icon + title + optional count chip
 *   - A divider-separated stack of child rows
 *   - An optional footer "View all →" link row
 *
 * Sections only render when they have content — callers are
 * responsible for the empty-section guard.
 */

interface SectionCardProps {
  icon: React.ReactNode;
  title: string;
  count?: number;
  children: React.ReactNode;
  /** If provided, renders a "View all →" footer row. */
  viewAllHref?: string;
  viewAllLabel?: string;
  className?: string;
}

export function SectionCard({
  icon,
  title,
  count,
  children,
  viewAllHref,
  viewAllLabel = "View all →",
  className,
}: SectionCardProps) {
  return (
    <section
      className={cn(
        "overflow-hidden rounded-2xl bg-bg-tertiary shadow-card",
        className,
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-4 pt-4 pb-3">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center text-label-secondary">
          {icon}
        </span>
        <h2 className="flex-1 text-title-3 text-label-primary">{title}</h2>
        {count !== undefined && count > 0 && (
          <span className="rounded-full bg-bg-elevated px-2 py-0.5 text-footnote font-medium tabular-nums text-label-secondary">
            {count}
          </span>
        )}
      </div>

      {/* Row stack */}
      <div className="divide-y divide-separator">{children}</div>

      {/* Footer "View all" link */}
      {viewAllHref && (
        <Link
          href={viewAllHref}
          className="flex min-h-[44px] items-center justify-between px-4 py-3 text-callout text-accent active:bg-bg-elevated/50 no-tap-highlight"
        >
          <span>{viewAllLabel}</span>
          <ChevronRight className="h-4 w-4 opacity-60" />
        </Link>
      )}
    </section>
  );
}
