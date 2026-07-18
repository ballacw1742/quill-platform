"use client";

import * as React from "react";
import { Scale } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * DraftAttorneyBanner — prominent, non-dismissible legal disclaimer that must
 * appear on every AI-drafted contract view (including print mode).
 *
 * Lovable redesign: Scale icon, warning design tokens (bg-warning/10,
 * border-warning/30, text-warning, text-caption). Non-dismissible.
 * Print: border opacity stays fully visible.
 */
export function DraftAttorneyBanner({ className }: { className?: string }) {
  return (
    <div
      role="alert"
      aria-live="polite"
      className={cn(
        "flex items-start gap-2 rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-caption text-warning",
        "print:border-warning/60 print:bg-warning/10",
        className,
      )}
    >
      <Scale
        className="mt-0.5 h-3.5 w-3.5 shrink-0"
        aria-hidden="true"
      />
      <p>
        AI-generated draft. Not legal advice — have licensed counsel review before
        executing.
      </p>
    </div>
  );
}

export default DraftAttorneyBanner;
