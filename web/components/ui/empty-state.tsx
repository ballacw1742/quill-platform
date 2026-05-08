"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * iOS-style empty state — DESIGN_SYSTEM §7 / §10.
 *
 * Centered: icon (56 px, label-tertiary), title (text-title-3, label-primary),
 * subtitle (text-body, label-secondary), optional ghost-style action button.
 *
 * Never an emoji. Apple doesn't, neither do we.
 */
export function EmptyState({
  icon,
  title,
  subtitle,
  action,
  className,
}: {
  icon?: React.ReactNode;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex flex-col items-center justify-center gap-3 px-6 py-16 text-center",
        className,
      )}
    >
      {icon && (
        <div className="flex h-14 w-14 items-center justify-center text-label-tertiary">
          <span className="[&>svg]:h-14 [&>svg]:w-14" aria-hidden="true">
            {icon}
          </span>
        </div>
      )}
      <div className="space-y-1">
        <div className="text-title-3 text-label-primary">{title}</div>
        {subtitle && (
          <p className="text-body text-label-secondary">{subtitle}</p>
        )}
      </div>
      {action && <div className="pt-3">{action}</div>}
    </div>
  );
}
