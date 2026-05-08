"use client";

import * as React from "react";
import {
  AnimatePresence,
  motion,
  useMotionValue,
  useTransform,
  useReducedMotion,
} from "framer-motion";
import { cn } from "@/lib/utils";

/**
 * iOS Mail-style swipe-action row.
 *
 * MOBILE_UX_SPEC §1 + DESIGN_SYSTEM §7:
 * - Swipe left → trailing actions (Approve / Reject).
 * - Swipe right → leading actions (Open / Snooze).
 * - 48 px partial reveal threshold; 96 px full commit threshold.
 * - Quick swipe past 50% commits the primary action without release.
 * - Haptic feedback (navigator.vibrate) on commit boundary cross.
 * - prefers-reduced-motion: disables drag entirely; consumers fall back to
 *   the row's own onTap for the primary action.
 *
 * The row is a controlled wrapper. The caller passes `children` (typically
 * a ListRow) and arrays of leading / trailing actions.
 */

export type SwipeAction = {
  key: string;
  label: string;
  icon?: React.ReactNode;
  /** Background color for the action chip (use design tokens). */
  tone: "success" | "danger" | "warning" | "accent" | "neutral";
  onAction: () => void;
  /** When true, this action commits on full swipe past 50%. Defaults to last action. */
  primary?: boolean;
};

const TONE_BG: Record<SwipeAction["tone"], string> = {
  success: "bg-success text-white",
  danger: "bg-danger text-white",
  warning: "bg-warning text-white",
  accent: "bg-accent text-white",
  neutral: "bg-bg-elevated text-label-primary",
};

const PARTIAL_REVEAL = 48;
const FULL_COMMIT = 96;

function vibrate(pattern: number | number[] = 10) {
  if (typeof navigator !== "undefined" && "vibrate" in navigator) {
    try {
      navigator.vibrate(pattern);
    } catch {
      /* noop */
    }
  }
}

export function SwipeRow({
  leading = [],
  trailing = [],
  children,
  className,
  /** When false, gestures are disabled; row renders inert. */
  enabled = true,
}: {
  leading?: SwipeAction[];
  trailing?: SwipeAction[];
  children: React.ReactNode;
  className?: string;
  enabled?: boolean;
}) {
  const reduceMotion = useReducedMotion();
  const x = useMotionValue(0);
  const [committedAt, setCommittedAt] = React.useState<number | null>(null);

  const dragEnabled = enabled && !reduceMotion;

  // Background-tray opacity ramps up with progress.
  const leadingOpacity = useTransform(x, [0, 24], [0, 1]);
  const trailingOpacity = useTransform(x, [-24, 0], [1, 0]);

  // Haptic on threshold crossing
  const lastBucket = React.useRef<"none" | "partial" | "full">("none");
  React.useEffect(() => {
    return x.on("change", (latest) => {
      const a = Math.abs(latest);
      let bucket: "none" | "partial" | "full" = "none";
      if (a >= FULL_COMMIT) bucket = "full";
      else if (a >= PARTIAL_REVEAL) bucket = "partial";
      if (bucket !== lastBucket.current) {
        lastBucket.current = bucket;
        if (bucket !== "none") vibrate(10);
      }
    });
  }, [x]);

  const trailingPrimary =
    trailing.find((a) => a.primary) ?? trailing[trailing.length - 1];
  const leadingPrimary = leading.find((a) => a.primary) ?? leading[0];

  const settle = (commit: SwipeAction | null) => {
    if (commit) {
      // animate offscreen briefly, fire action, snap back
      vibrate([12, 4, 18]);
      setCommittedAt(Date.now());
      Promise.resolve().then(() => commit.onAction());
    }
    // snap back
    void x.set(0);
    lastBucket.current = "none";
  };

  return (
    <div
      className={cn(
        "relative isolate overflow-hidden bg-bg-tertiary",
        className,
      )}
    >
      {/* Leading tray (visible on swipe-right) */}
      {leading.length > 0 && dragEnabled && (
        <motion.div
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 left-0 flex items-stretch"
          style={{ opacity: leadingOpacity }}
        >
          {leading.map((a) => (
            <ActionChip key={a.key} action={a} side="leading" />
          ))}
        </motion.div>
      )}
      {/* Trailing tray (visible on swipe-left) */}
      {trailing.length > 0 && dragEnabled && (
        <motion.div
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 right-0 flex items-stretch"
          style={{ opacity: trailingOpacity }}
        >
          {trailing.map((a) => (
            <ActionChip key={a.key} action={a} side="trailing" />
          ))}
        </motion.div>
      )}

      <motion.div
        className="relative bg-bg-tertiary touch-pan-y"
        style={{ x }}
        drag={dragEnabled ? "x" : false}
        dragDirectionLock
        dragConstraints={{ left: -240, right: 240 }}
        dragElastic={0.05}
        dragMomentum={false}
        onDragEnd={(_e, info) => {
          const dx = info.offset.x;
          const vx = info.velocity.x;
          // Trailing (left swipe → negative dx)
          if (dx < 0 && trailing.length > 0) {
            const fullCommit = -dx > FULL_COMMIT || -vx > 600;
            const partialReveal = -dx > PARTIAL_REVEAL && -dx <= FULL_COMMIT;
            if (fullCommit && trailingPrimary) {
              settle(trailingPrimary);
              return;
            }
            if (partialReveal) {
              // Snap to partial-reveal so user can tap an action chip.
              const w = trailing.length * 96;
              x.set(-Math.min(w, 96 * trailing.length));
              return;
            }
          }
          // Leading (right swipe → positive dx)
          if (dx > 0 && leading.length > 0) {
            const fullCommit = dx > FULL_COMMIT || vx > 600;
            const partialReveal = dx > PARTIAL_REVEAL && dx <= FULL_COMMIT;
            if (fullCommit && leadingPrimary) {
              settle(leadingPrimary);
              return;
            }
            if (partialReveal) {
              x.set(Math.min(96, 96 * leading.length));
              return;
            }
          }
          // Otherwise snap back.
          x.set(0);
        }}
        animate={committedAt ? { opacity: 0.5 } : { opacity: 1 }}
        transition={{ duration: 0.18, ease: [0.32, 0.72, 0, 1] }}
      >
        {children}
      </motion.div>
    </div>
  );
}

function ActionChip({
  action,
  side,
}: {
  action: SwipeAction;
  side: "leading" | "trailing";
}) {
  return (
    <button
      type="button"
      onClick={action.onAction}
      aria-label={action.label}
      className={cn(
        "flex min-w-[88px] items-center justify-center gap-1 px-4 text-headline font-medium pointer-events-auto",
        TONE_BG[action.tone],
        side === "trailing" ? "border-l border-black/5" : "border-r border-black/5",
      )}
    >
      <span className="flex flex-col items-center gap-1">
        {action.icon && <span aria-hidden="true">{action.icon}</span>}
        <span className="text-caption-1">{action.label}</span>
      </span>
    </button>
  );
}
