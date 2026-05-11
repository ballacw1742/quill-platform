"use client";

import * as React from "react";
import { ShieldAlert } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * DraftAttorneyBanner — prominent, non-dismissible amber alert that must
 * appear on every AI-drafted contract view (including print mode).
 *
 * Design: rounded card with amber border + background, ShieldAlert icon,
 * bold canonical legal disclaimer text.
 */
export function DraftAttorneyBanner({ className }: { className?: string }) {
  return (
    <div
      role="alert"
      aria-live="polite"
      className={cn(
        "flex items-start gap-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3",
        // Print: keep visible, don't hide
        "print:border-amber-400 print:bg-amber-50",
        className,
      )}
    >
      <ShieldAlert
        className="mt-0.5 h-5 w-5 shrink-0 text-amber-600"
        aria-hidden="true"
      />
      <p className="text-sm font-medium leading-snug text-amber-900">
        <span className="font-semibold">AI-generated draft contract — requires attorney review.</span>{" "}
        Do not execute, send, or rely on this draft for any binding obligation without review by
        qualified legal counsel.
      </p>
    </div>
  );
}

export default DraftAttorneyBanner;
