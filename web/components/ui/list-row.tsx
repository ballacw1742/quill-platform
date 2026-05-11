"use client";

import * as React from "react";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * iOS list row — the workhorse pattern from DESIGN_SYSTEM §7 + MOBILE_UX_SPEC §1.
 *
 *   ┌──────────────────────────────────────────────────────┐
 *   │ [icon]  Title (text-headline)            [chip] [ > ] │
 *   │         Subtitle (text-callout, label-secondary, 2L)  │
 *   └──────────────────────────────────────────────────────┘
 *
 * - 56 px minimum tap height (DESIGN_SYSTEM §7).
 * - Hairline separator between rows (use ListGroup wrapper for grouped style).
 * - Tap target = entire row.
 * - chevron only present if onClick / href is wired.
 * - Tap state: opacity 0.6 with 100 ms transition (active class).
 */

export type ListRowProps = {
  /** Leading icon — small (20–24 px). Pass a lucide icon or any element. */
  icon?: React.ReactNode;
  /** Optional accent colour for the icon container. */
  iconTone?: "neutral" | "accent" | "success" | "warning" | "danger" | "info";
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  /** Right-side chip (e.g. "2h", count, status pill). */
  chip?: React.ReactNode;
  /** Show chevron — defaults to true if href / onClick is set. */
  chevron?: boolean;
  href?: string;
  onClick?: () => void;
  className?: string;
  /** Left-most accent stripe (e.g. red on critical-flagged rows). */
  accent?: "danger" | "warning" | "success" | "accent";
  /** Disable the divider beneath this row (last in group, etc.). */
  hideDivider?: boolean;
  /** Optional aria-label override for icon-only or non-text rows. */
  ariaLabel?: string;
  /** Inline footer below subtitle (e.g. flag chips, age). */
  footer?: React.ReactNode;
  /** Replace default chevron with custom right-side trailing element. */
  trailing?: React.ReactNode;
};

const TONE_CLASS: Record<NonNullable<ListRowProps["iconTone"]>, string> = {
  neutral: "bg-bg-elevated text-label-secondary",
  accent: "bg-accent/10 text-accent",
  success: "bg-success/10 text-success",
  warning: "bg-warning/10 text-warning",
  danger: "bg-danger/10 text-danger",
  info: "bg-info/10 text-info",
};

export const ListRow = React.forwardRef<HTMLDivElement, ListRowProps>(function ListRow(
  {
    icon,
    iconTone = "neutral",
    title,
    subtitle,
    chip,
    chevron,
    href,
    onClick,
    className,
    accent,
    hideDivider,
    ariaLabel,
    footer,
    trailing,
  },
  ref,
) {
  const interactive = !!href || !!onClick;
  const showChevron = chevron ?? interactive;

  const inner = (
    <div
      className={cn(
        "relative flex w-full items-center gap-3 px-4 py-3",
        "min-h-[56px] no-select",
        accent && "before:absolute before:left-0 before:top-2 before:bottom-2 before:w-[3px] before:rounded-r-full",
        accent === "danger" && "before:bg-danger",
        accent === "warning" && "before:bg-warning",
        accent === "success" && "before:bg-success",
        accent === "accent" && "before:bg-accent",
        interactive && "active:bg-bg-elevated/60 transition-colors duration-tap",
      )}
    >
      {icon !== undefined && icon !== null && (
        <span
          className={cn(
            "flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
            TONE_CLASS[iconTone],
          )}
          aria-hidden="true"
        >
          {icon}
        </span>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 text-headline text-label-primary">
          <span className="truncate">{title}</span>
        </div>
        {subtitle && (
          <div className="line-clamp-2 text-callout text-label-secondary">
            {subtitle}
          </div>
        )}
        {footer && <div className="mt-1.5">{footer}</div>}
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {chip !== undefined && (
          <span className="text-footnote text-label-tertiary">{chip}</span>
        )}
        {trailing}
        {showChevron && !trailing && (
          <ChevronRight
            className="h-4 w-4 text-label-quaternary"
            aria-hidden="true"
          />
        )}
      </div>
      {!hideDivider && (
        <span
          className="pointer-events-none absolute bottom-0 right-0 h-px bg-separator/40"
          style={{ left: icon !== undefined && icon !== null ? "60px" : "16px" }}
          aria-hidden="true"
        />
      )}
    </div>
  );

  if (href) {
    // Use Next.js Link for client-side nav so the page doesn't fully reload
    // — a hard <a> navigation can leave the page in an unresponsive state
    // (e.g. the tab bar stops responding) until the new bundle compiles.
    return (
      <Link
        ref={ref as unknown as React.Ref<HTMLAnchorElement>}
        href={href}
        aria-label={ariaLabel}
        className={cn("block no-tap-highlight", className)}
      >
        {inner}
      </Link>
    );
  }
  if (onClick) {
    return (
      <button
        type="button"
        ref={ref as unknown as React.Ref<HTMLButtonElement>}
        onClick={onClick}
        aria-label={ariaLabel}
        className={cn(
          "block w-full text-left no-tap-highlight",
          className,
        )}
      >
        {inner}
      </button>
    );
  }
  return (
    <div ref={ref} className={cn(className)} aria-label={ariaLabel}>
      {inner}
    </div>
  );
});
