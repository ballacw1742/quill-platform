"use client";

/**
 * Collapsible.tsx — lightweight headless collapsible primitive.
 *
 * Not using Radix Accordion here: Accordion has single-open-at-a-time
 * semantics by default, and the Queue category groups allow multiple
 * sections open simultaneously.
 *
 * Mobile-first: CollapsibleTrigger enforces min-h-[44px] touch target.
 */

import * as React from "react";
import { cn } from "@/lib/utils";

// ── Collapsible (wrapper) ────────────────────────────────────────────────────

interface CollapsibleProps {
  open: boolean;
  onOpenChange?: (open: boolean) => void;
  children: React.ReactNode;
  className?: string;
}

export function Collapsible({ open, children, className }: CollapsibleProps) {
  return (
    <div className={cn("", className)} data-state={open ? "open" : "closed"}>
      {children}
    </div>
  );
}

// ── CollapsibleTrigger ───────────────────────────────────────────────────────

interface CollapsibleTriggerProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onClick" | "aria-expanded"> {
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
  className?: string;
}

export function CollapsibleTrigger({
  open,
  onToggle,
  children,
  className,
  ...rest
}: CollapsibleTriggerProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      className={cn(
        // Mobile touch target per MOBILE_UX_SPEC: min 44px height.
        "flex w-full items-center min-h-[44px] text-left no-tap-highlight active:opacity-70",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

// ── CollapsibleContent ───────────────────────────────────────────────────────

interface CollapsibleContentProps {
  open: boolean;
  children: React.ReactNode;
  className?: string;
}

export function CollapsibleContent({
  open,
  children,
  className,
}: CollapsibleContentProps) {
  if (!open) return null;
  return <div className={cn("", className)}>{children}</div>;
}
