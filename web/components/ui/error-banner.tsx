"use client";

import * as React from "react";
import { AlertCircle, RotateCw } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * ErrorBanner — inline, non-blocking error surface for failed list
 * fetches (TanStack Query `error` state). Renders ABOVE the list, so the
 * existing screen layout stays intact and the user can still see whatever
 * cached data is available.
 *
 * Per COPY_GUIDE.md §"Loading & error states":
 *   - Lead with what happened in plain language (no API/HTTP jargon).
 *   - Provide an action: \"Try again\" or \"Reload.\"
 *
 * Visuals (per DESIGN_SYSTEM):
 *   - Rounded card on bg-tertiary
 *   - 3px danger left-accent border
 *   - label-secondary message text
 *   - Optional action pill on the right
 */
export function ErrorBanner({
  message,
  onRetry,
  className,
  retryLabel = "Try again",
}: {
  message: string;
  onRetry?: () => void;
  className?: string;
  retryLabel?: string;
}) {
  return (
    <div
      role="alert"
      aria-live="polite"
      className={cn(
        "flex items-start gap-3 rounded-lg bg-bg-tertiary p-3 mx-4 my-2",
        "border-l-[3px] border-danger",
        className,
      )}
    >
      <AlertCircle
        className="h-5 w-5 shrink-0 text-danger mt-0.5"
        aria-hidden="true"
      />
      <div className="flex-1 min-w-0 text-callout text-label-secondary leading-snug">
        {message}
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className={cn(
            "inline-flex items-center gap-1 shrink-0 rounded-md px-3 py-1.5",
            "text-callout font-medium text-accent active:opacity-60 no-tap-highlight",
            "min-h-[36px]",
          )}
        >
          <RotateCw className="h-4 w-4" aria-hidden="true" />
          {retryLabel}
        </button>
      )}
    </div>
  );
}
