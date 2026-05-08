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
  MessageCircle,
  Newspaper,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * OnboardingOverlay — four-step intro shown the first time a signed-in
 * user lands on /queue.
 *
 * Per COPY_GUIDE.md §"Onboarding overlay":
 *   1. "Quill is your project assistant."
 *   2. "Tap Approve, Reject, or Edit on any item."
 *   3. "Use Today for a daily summary."
 *   4. (Phase E) "Chat with Quill on Telegram." — always shown; the
 *      Telegram bot is universally useful and the card invites pairing
 *      regardless of current status.
 *
 * Behaviour:
 *   - Dismissible with the top-right "Skip" button (sets the flag).
 *   - Final card has "Got it" instead of "Next"; tapping it plays a subtle
 *     scale-from-0.95 fade celebration before unmounting (no confetti).
 *   - Sets `localStorage.quill.onboarded = "true"` on every dismiss path.
 *   - Swipe horizontally between cards (drag-end threshold + arrow keys
 *     + dot indicator). Spring uses the iOS curve from DESIGN_SYSTEM §6.
 *   - Reduced-motion: no slide animation, instant card swap, no
 *     celebration scale; just instant state changes.
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
  {
    icon: MessageCircle,
    title: "Chat with Quill on Telegram.",
    body: "Plain English works too. Tap @DC_QuillBot to start a conversation.",
  },
];

const SWIPE_THRESHOLD_PX = 50;
const IOS_EASE: [number, number, number, number] = [0.32, 0.72, 0, 1];

export function OnboardingOverlay() {
  const reduceMotion = useReducedMotion();
  const [open, setOpen] = React.useState(false);
  const [index, setIndex] = React.useState(0);
  const [direction, setDirection] = React.useState<1 | -1>(1);
  const [closing, setClosing] = React.useState(false);

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

  const persistFlag = React.useCallback(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, "true");
    } catch {
      // ignore
    }
  }, []);

  const skip = React.useCallback(() => {
    persistFlag();
    setOpen(false);
  }, [persistFlag]);

  // Final-card "Got it" celebration: a brief scale-from-0.95 fade. We mark
  // closing=true, let the exit animation play (~220 ms), then unmount.
  const finishWithCelebration = React.useCallback(() => {
    persistFlag();
    if (reduceMotion) {
      setOpen(false);
      return;
    }
    setClosing(true);
    window.setTimeout(() => setOpen(false), 240);
  }, [persistFlag, reduceMotion]);

  const next = React.useCallback(() => {
    if (index >= CARDS.length - 1) {
      finishWithCelebration();
      return;
    }
    setDirection(1);
    setIndex((i) => Math.min(i + 1, CARDS.length - 1));
  }, [index, finishWithCelebration]);

  const prev = React.useCallback(() => {
    setDirection(-1);
    setIndex((i) => Math.max(i - 1, 0));
  }, []);

  // Escape → skip; arrow keys page between cards.
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") skip();
      if (e.key === "ArrowRight") next();
      if (e.key === "ArrowLeft") prev();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, next, prev, skip]);

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

  // Card slide variants — tuned for iOS-native feel: small offset, tween
  // (not spring) so there's no overshoot, ~240 ms duration.
  const cardVariants = reduceMotion
    ? {
        enter: { opacity: 1, x: 0 },
        center: { opacity: 1, x: 0 },
        exit: { opacity: 0, x: 0 },
      }
    : {
        enter: (dir: 1 | -1) => ({ opacity: 0, x: dir * 32 }),
        center: { opacity: 1, x: 0 },
        exit: (dir: 1 | -1) => ({ opacity: 0, x: dir * -32 }),
      };

  return (
    <motion.div
      role="dialog"
      aria-modal="true"
      aria-labelledby="onboarding-title"
      className="fixed inset-0 z-[60] flex flex-col bg-bg"
      initial={reduceMotion ? false : { opacity: 0 }}
      animate={
        closing
          ? { opacity: 0, scale: reduceMotion ? 1 : 0.97 }
          : { opacity: 1, scale: 1 }
      }
      transition={{ duration: reduceMotion ? 0 : 0.22, ease: IOS_EASE }}
      style={{ transformOrigin: "center" }}
    >
      {/* Top bar — Skip lives here; even Skip sets the flag. */}
      <div className="flex h-12 items-center justify-end px-2 pt-safe">
        <button
          type="button"
          onClick={skip}
          className="text-body text-accent active:opacity-60 no-tap-highlight min-h-[44px] px-3"
          aria-label="Skip onboarding"
        >
          Skip
        </button>
      </div>

      {/* Card area */}
      <div className="flex-1 flex items-center justify-center px-6">
        <AnimatePresence mode="wait" initial={false} custom={direction}>
          <motion.div
            key={index}
            custom={direction}
            variants={cardVariants}
            initial="enter"
            animate="center"
            exit="exit"
            transition={{
              duration: reduceMotion ? 0 : 0.24,
              ease: IOS_EASE,
            }}
            drag={reduceMotion ? false : "x"}
            dragElastic={0.18}
            dragConstraints={{ left: 0, right: 0 }}
            dragMomentum={false}
            onDragEnd={onDragEnd}
            className="flex max-w-md flex-col items-center text-center gap-5 touch-pan-y"
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
      <div className="flex flex-col items-center gap-5 px-6 pt-4 pb-[max(env(safe-area-inset-bottom),24px)]">
        <div
          className="flex items-center gap-2"
          role="tablist"
          aria-label="Onboarding progress"
        >
          {CARDS.map((_, i) => (
            <button
              key={i}
              type="button"
              role="tab"
              aria-selected={i === index}
              aria-label={`Step ${i + 1} of ${CARDS.length}`}
              tabIndex={-1}
              onClick={() => {
                setDirection(i > index ? 1 : -1);
                setIndex(i);
              }}
              className={cn(
                "h-2 rounded-full transition-all",
                i === index
                  ? "w-6 bg-accent"
                  : "w-2 bg-label-quaternary/40 hover:bg-label-tertiary/60",
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
            "transition-transform duration-100 active:scale-[0.98]",
          )}
        >
          {isLast ? "Got it" : "Next"}
        </button>
      </div>
    </motion.div>
  );
}
