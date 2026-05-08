"use client";

import * as React from "react";
import {
  motion,
  AnimatePresence,
  useReducedMotion,
  type PanInfo,
} from "framer-motion";
import {
  CheckCircle2,
  Newspaper,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * OnboardingOverlay — three-step intro shown the first time a signed-in
 * user lands on /queue.
 *
 * Per COPY_GUIDE.md §"Onboarding overlay":
 *   1. "Quill is your project assistant."
 *   2. "Tap Approve, Reject, or Edit on any item."
 *   3. "Use Today for a daily summary."
 *
 * Behaviour:
 *   - Dismissible with the top-right "Skip" button (sets the flag).
 *   - Final card has "Got it" instead of "Next" (also sets the flag).
 *   - Sets `localStorage.quill.onboarded = "true"` on every dismiss path.
 *   - Swipe horizontally between cards (and dot indicator + Next button).
 *   - Reduced-motion: no slide animation, just instant card swap.
 *   - Honours focus trap via fixed-position overlay; pressing Escape
 *     dismisses (treated as skip).
 */

const STORAGE_KEY = "quill.onboarded";

type Card = {
  icon: LucideIcon;
  title: string;
  body: string;
};

const CARDS: Card[] = [
  {
    icon: Sparkles,
    title: "Quill is your project assistant.",
    body: "A panel of helpers reads incoming work and prepares it for your sign-off.",
  },
  {
    icon: CheckCircle2,
    title: "Tap Approve, Reject, or Edit on any item.",
    body: "You're always in control. Nothing happens without your sign-off.",
  },
  {
    icon: Newspaper,
    title: "Use Today for a daily summary.",
    body: "At 7 AM, you'll get a brief of what needs your attention.",
  },
];

const SWIPE_THRESHOLD_PX = 50;

export function OnboardingOverlay() {
  const reduceMotion = useReducedMotion();
  const [open, setOpen] = React.useState(false);
  const [index, setIndex] = React.useState(0);

  // Run on mount; show iff the flag isn't set.
  React.useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      if (window.localStorage.getItem(STORAGE_KEY) !== "true") {
        setOpen(true);
      }
    } catch {
      // localStorage unavailable (private mode, SSR-pre-hydrate) — skip.
    }
  }, []);

  const dismiss = React.useCallback(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, "true");
    } catch {
      // ignore
    }
    setOpen(false);
  }, []);

  const next = () => {
    if (index >= CARDS.length - 1) {
      dismiss();
      return;
    }
    setIndex((i) => Math.min(i + 1, CARDS.length - 1));
  };

  const prev = () => setIndex((i) => Math.max(i - 1, 0));

  // Escape → skip
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") dismiss();
      if (e.key === "ArrowRight") next();
      if (e.key === "ArrowLeft") prev();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, index]);

  if (!open) return null;

  const card = CARDS[index];
  const isLast = index === CARDS.length - 1;
  const Icon = card.icon;

  const onDragEnd = (
    _e: MouseEvent | TouchEvent | PointerEvent,
    info: PanInfo,
  ) => {
    if (info.offset.x < -SWIPE_THRESHOLD_PX) next();
    else if (info.offset.x > SWIPE_THRESHOLD_PX) prev();
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="onboarding-title"
      className="fixed inset-0 z-[60] flex flex-col bg-bg"
    >
      {/* Top bar — Skip lives here; even Skip sets the flag. */}
      <div className="flex h-12 items-center justify-end px-2 pt-[env(safe-area-inset-top)]">
        <button
          type="button"
          onClick={dismiss}
          className="text-body text-accent active:opacity-60 no-tap-highlight min-h-[44px] px-3"
        >
          Skip
        </button>
      </div>

      {/* Card area */}
      <div className="flex-1 flex items-center justify-center px-6">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={index}
            drag={reduceMotion ? false : "x"}
            dragElastic={0.1}
            dragConstraints={{ left: 0, right: 0 }}
            onDragEnd={onDragEnd}
            initial={reduceMotion ? { opacity: 1 } : { opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={reduceMotion ? { opacity: 0 } : { opacity: 0, x: -24 }}
            transition={{ duration: reduceMotion ? 0 : 0.24 }}
            className="flex max-w-md flex-col items-center text-center gap-5"
          >
            <div className="flex h-20 w-20 items-center justify-center rounded-full bg-accent/10 text-accent">
              <Icon className="h-10 w-10" aria-hidden="true" />
            </div>
            <h1
              id="onboarding-title"
              className="text-title-2 text-label-primary leading-tight"
            >
              {card.title}
            </h1>
            <p className="text-body text-label-secondary leading-relaxed">
              {card.body}
            </p>
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Dot indicator + primary action */}
      <div className="flex flex-col items-center gap-5 px-6 pb-[max(env(safe-area-inset-bottom),24px)] pt-4">
        <div className="flex items-center gap-2" aria-hidden="true">
          {CARDS.map((_, i) => (
            <span
              key={i}
              className={cn(
                "h-2 rounded-full transition-all",
                i === index
                  ? "w-6 bg-accent"
                  : "w-2 bg-label-quaternary/40",
              )}
            />
          ))}
        </div>
        <button
          type="button"
          onClick={next}
          className={cn(
            "flex h-12 w-full max-w-md items-center justify-center rounded-lg",
            "bg-accent text-headline font-medium text-white",
            "active:opacity-80 no-tap-highlight",
          )}
        >
          {isLast ? "Got it" : "Next"}
        </button>
      </div>
    </div>
  );
}
