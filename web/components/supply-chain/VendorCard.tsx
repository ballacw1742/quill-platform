"use client";

import { Factory } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Vendor } from "@/lib/schemas";

/**
 * VendorCard — ported from Lovable
 * quill-platform-builder/src/components/quill/supply-chain/VendorCard.tsx
 *
 * Uses prod design tokens verbatim; no inline hex, no Builder-style imports.
 * Vendor type comes from prod lib/schemas.ts.
 */
export function VendorCard({ vendor }: { vendor: Vendor }) {
  return (
    <div
      className={cn(
        "rounded-2xl bg-bg-elevated shadow-card p-5 mb-2.5",
        "flex flex-col gap-3",
      )}
    >
      {/* Header row: name + badges */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-3 min-w-0">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-accent/10 text-accent">
            <Factory className="h-6 w-6" />
          </span>
          <span className="text-headline font-semibold text-label-primary truncate">
            {vendor.name}
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-footnote font-semibold text-accent bg-accent/10 rounded-full px-2 py-0.5 capitalize">
            {vendor.category}
          </span>
          {vendor.prequalified && (
            <span className="text-footnote font-semibold text-accent bg-accent/10 rounded-full px-2 py-0.5">
              Approved
            </span>
          )}
        </div>
      </div>

      {/* Stats row */}
      <div className="flex items-center gap-3 flex-wrap">
        {vendor.performance_score != null && (
          <span className="text-subhead text-label-secondary">
            Score:{" "}
            <span className="text-label-primary font-bold tabular-nums">
              {vendor.performance_score.toFixed(1)}/10
            </span>
          </span>
        )}
        {vendor.contact_name && (
          <span className="text-subhead text-label-secondary truncate">
            {vendor.contact_name}
          </span>
        )}
        {vendor.contact_email && (
          <span className="text-footnote text-label-tertiary truncate">
            {vendor.contact_email}
          </span>
        )}
      </div>
    </div>
  );
}
