"use client";

import * as React from "react";
import { motion, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";

/**
 * iOS-style segmented control.
 *
 * - Pill-shaped track in `--bg-elevated` (iOS systemFill).
 * - Selected segment has an elevated `--bg-tertiary` background that animates
 *   with a layoutId-driven slide (matches iOS UISegmentedControl).
 * - role="tablist" + role="tab" so swipeable lane switching is accessible.
 * - DESIGN_SYSTEM §10 — reduced-motion disables the slide.
 *
 * The layout-shift trick uses framer-motion's shared `layoutId` so the
 * highlighted pill physically moves between segments rather than re-rendering.
 *
 * Used on /queue (lane switcher) and elsewhere a 2–4-way switch is wanted.
 */

export type SegmentedOption<T extends string> = {
  value: T;
  label: React.ReactNode;
  /** Optional small chip / count rendered next to the label. */
  badge?: React.ReactNode;
};

export function SegmentedControl<T extends string>({
  value,
  onChange,
  options,
  className,
  ariaLabel,
}: {
  value: T;
  onChange: (next: T) => void;
  options: ReadonlyArray<SegmentedOption<T>>;
  className?: string;
  ariaLabel?: string;
}) {
  const reduceMotion = useReducedMotion();
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn(
        "inline-flex w-full items-stretch rounded-md bg-bg-elevated p-[2px]",
        "min-h-[32px]",
        className,
      )}
    >
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            role="tab"
            type="button"
            aria-selected={active}
            onClick={() => onChange(opt.value)}
            className={cn(
              "relative min-w-0 flex-1 min-h-[32px] rounded-[8px] px-2 no-tap-highlight",
              "flex items-center justify-center gap-1.5",
              "text-subhead font-medium transition-colors duration-state",
              active ? "text-label-primary" : "text-label-secondary active:text-label-primary",
            )}
          >
            {active && (
              <motion.span
                layoutId="segmented-pill"
                className="absolute inset-0 rounded-[8px] bg-bg-tertiary shadow-card"
                transition={
                  reduceMotion
                    ? { duration: 0 }
                    : { type: "spring", stiffness: 500, damping: 40, mass: 0.6 }
                }
                aria-hidden="true"
              />
            )}
            <span className="relative z-10 truncate">{opt.label}</span>
            {opt.badge !== undefined && (
              <span
                className={cn(
                  "relative z-10 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full px-1 text-caption-2 font-semibold tabular-nums",
                  active
                    ? "bg-label-primary/10 text-label-primary"
                    : "bg-label-quaternary/30 text-label-secondary",
                )}
              >
                {opt.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
