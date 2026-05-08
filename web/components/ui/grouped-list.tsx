"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * iOS Settings-style grouped list.
 *
 * Layout per DESIGN_SYSTEM §7 + MOBILE_UX_SPEC §"Tab 4 — Profile":
 *
 *   SECTION HEADER (text-caption-1 small caps, label-secondary, padded 12 + 4 px)
 *   ┌───────────────────────────────┐
 *   │ Row                          >│  (rounded-lg radius-lg, bg-tertiary)
 *   │ ─────────────────────────     │
 *   │ Row                          >│
 *   └───────────────────────────────┘
 *   Optional footer caption (text-footnote, label-tertiary, padded)
 */

export function GroupedList({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("bg-bg-elevated min-h-full", className)}>
      <div className="flex flex-col gap-6 px-4 py-4">{children}</div>
    </div>
  );
}

export function ListGroup({
  title,
  footer,
  children,
  className,
}: {
  title?: React.ReactNode;
  footer?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("flex flex-col gap-1.5", className)}>
      {title && (
        <h3 className="px-4 text-caption-1 uppercase tracking-wider text-label-secondary">
          {title}
        </h3>
      )}
      <div className="overflow-hidden rounded-lg bg-bg-tertiary shadow-card">
        {children}
      </div>
      {footer && (
        <div className="px-4 text-footnote text-label-tertiary">{footer}</div>
      )}
    </section>
  );
}
