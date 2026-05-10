"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * StatPill — number + label combo for headline stats.
 * Used in hero sections of artifact views.
 */
export function StatPill({
  value,
  label,
  subValue,
  accent = false,
  className,
}: {
  value: React.ReactNode;
  label: string;
  subValue?: string;
  accent?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-start rounded-xl px-4 py-3",
        accent ? "bg-accent/10" : "bg-bg-elevated",
        className,
      )}
    >
      <div
        className={cn(
          "text-title-2 font-bold tabular-nums leading-tight",
          accent ? "text-accent" : "text-label-primary",
        )}
      >
        {value}
      </div>
      {subValue && (
        <div className="text-footnote text-label-tertiary tabular-nums">
          {subValue}
        </div>
      )}
      <div className="text-caption-1 text-label-secondary mt-0.5">{label}</div>
    </div>
  );
}
