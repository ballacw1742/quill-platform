"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * ArtifactCard — iOS-style rounded card primitive.
 * Matches the bg-bg-tertiary / shadow-card pattern used across the app.
 */
export function ArtifactCard({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-xl bg-bg-tertiary shadow-card overflow-hidden",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function ArtifactCardHeader({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("px-4 pt-4 pb-3", className)} {...props}>
      {children}
    </div>
  );
}

export function ArtifactCardBody({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("px-4 pb-4", className)} {...props}>
      {children}
    </div>
  );
}
