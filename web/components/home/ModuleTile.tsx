"use client";

import * as React from "react";
import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * ModuleTile — iOS-app-icon-style squircle tile for the home grid
 * (UI_REDESIGN_BRIEF §3).
 *
 * - Squircle: rounded-[28%] approximation of the iOS icon shape.
 * - Per-module gradient tint behind a lucide line icon.
 * - Label below in Footnote (13px), wraps to 2 lines, never truncated.
 * - Optional badge count (e.g. pending approvals) pinned top-right.
 * - Spring press: scale 0.96 with the iOS easing curve.
 * - Whole tile is the touch target (≥ 44pt in both axes).
 */
export function ModuleTile({
  href,
  label,
  icon: Icon,
  gradient,
  badge,
  className,
}: {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Tailwind gradient classes, e.g. "from-indigo-500 to-violet-600" */
  gradient: string;
  badge?: number;
  className?: string;
}) {
  const [pressed, setPressed] = React.useState(false);

  return (
    <Link
      href={href}
      data-module-tile
      aria-label={badge ? `${label}, ${badge} pending` : label}
      onPointerDown={() => setPressed(true)}
      onPointerUp={() => setPressed(false)}
      onPointerLeave={() => setPressed(false)}
      onPointerCancel={() => setPressed(false)}
      className={cn(
        "flex min-h-[44px] min-w-[44px] flex-col items-center gap-1.5",
        "no-tap-highlight transition-transform duration-tap ease-ios",
        pressed ? "scale-[0.96]" : "scale-100",
        className,
      )}
    >
      <span
        className={cn(
          "relative flex aspect-square w-full max-w-[76px] items-center justify-center",
          "rounded-[28%] bg-gradient-to-br text-white",
          "shadow-[0_2px_8px_rgba(0,0,0,0.14),inset_0_1px_0_rgba(255,255,255,0.25)]",
          gradient,
        )}
      >
        <Icon className="h-[45%] w-[45%]" strokeWidth={1.8} aria-hidden="true" />
        {badge != null && badge > 0 && (
          <span
            className="absolute -right-1.5 -top-1.5 inline-flex min-w-[20px] items-center justify-center rounded-full bg-danger px-1.5 py-0.5 text-caption-2 font-semibold leading-none text-white shadow-elevated"
            aria-hidden="true"
          >
            {badge > 99 ? "99+" : badge}
          </span>
        )}
      </span>
      <span className="w-full text-center text-footnote font-medium leading-tight text-label-primary">
        {label}
      </span>
    </Link>
  );
}
