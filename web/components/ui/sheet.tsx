"use client";

import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { motion, useMotionValue, useReducedMotion } from "framer-motion";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * iOS-style bottom sheet primitive.
 *
 * - Slides up from bottom; rounded top corners (radius-2xl per DESIGN_SYSTEM §5).
 * - Drag-handle at top + drag-to-dismiss (>100 px or 50% velocity → close).
 * - Backdrop is 50% black; tap-to-dismiss.
 * - role="dialog" aria-modal="true" via Radix.
 * - Reduced-motion: skip the slide entirely (instant in/out).
 *
 * Backwards-compat: the previous Radix-side-sheet API (Sheet, SheetTrigger,
 * SheetContent side="right" | "left" | "top" | "bottom" + SheetHeader / Title /
 * Description / Close) is preserved as the same names so existing components
 * (AppShell account drawer etc.) don't break. New code should prefer
 * BottomSheet / BottomSheetContent for the iOS pattern.
 */

export const Sheet = DialogPrimitive.Root;
export const SheetTrigger = DialogPrimitive.Trigger;
export const SheetClose = DialogPrimitive.Close;

/* ── Legacy side-sheet (kept for AppShell backwards compat) ─────────────── */

import { cva, type VariantProps } from "class-variance-authority";

const sheetSideVariants = cva(
  "fixed z-50 gap-4 bg-bg p-6 shadow-elevated transition ease-ios data-[state=open]:animate-in data-[state=closed]:animate-out duration-state",
  {
    variants: {
      side: {
        top: "inset-x-0 top-0 border-b border-separator/40 rounded-b-2xl",
        bottom:
          "inset-x-0 bottom-0 border-t border-separator/40 rounded-t-2xl",
        left: "inset-y-0 left-0 h-full w-3/4 border-r border-separator/40 sm:max-w-sm",
        right:
          "inset-y-0 right-0 h-full w-3/4 border-l border-separator/40 sm:max-w-md",
      },
    },
    defaultVariants: { side: "right" },
  },
);

interface SheetContentProps
  extends React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>,
    VariantProps<typeof sheetSideVariants> {}

export const SheetContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  SheetContentProps
>(({ side = "right", className, children, ...props }, ref) => (
  <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm" />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(sheetSideVariants({ side }), className)}
      {...props}
    >
      {children}
      <DialogPrimitive.Close
        className="absolute right-4 top-4 rounded-sm opacity-70 hover:opacity-100"
        aria-label="Close"
      >
        <X className="h-4 w-4" />
        <span className="sr-only">Close</span>
      </DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
));
SheetContent.displayName = "SheetContent";

export const SheetHeader = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("flex flex-col gap-2 text-left", className)} {...props} />
);
SheetHeader.displayName = "SheetHeader";

export const SheetTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn("text-headline text-label-primary", className)}
    {...props}
  />
));
SheetTitle.displayName = "SheetTitle";

export const SheetDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn("text-callout text-label-secondary", className)}
    {...props}
  />
));
SheetDescription.displayName = "SheetDescription";

/* ── Drawer aliases (existing imports) ──────────────────────────────────── */

export const Drawer = Sheet;
export const DrawerTrigger = SheetTrigger;
export const DrawerContent = SheetContent;
export const DrawerHeader = SheetHeader;
export const DrawerTitle = SheetTitle;
export const DrawerDescription = SheetDescription;
export const DrawerClose = SheetClose;

/* ── BottomSheet — the iOS bottom sheet (preferred for new code) ────────── */

const DRAG_DISMISS_THRESHOLD_PX = 100;
const DRAG_DISMISS_VELOCITY = 500; // px/s

export type BottomSheetProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
  /** When true, renders a full-screen sheet (92% viewport). Default content-driven height. */
  fullHeight?: boolean;
  /** ARIA-label for the dialog. */
  ariaLabel?: string;
  /** Allow drag-to-dismiss (default true). */
  dismissible?: boolean;
};

export function BottomSheet({
  open,
  onOpenChange,
  children,
  fullHeight = false,
  ariaLabel,
  dismissible = true,
}: BottomSheetProps) {
  const reduceMotion = useReducedMotion();
  const y = useMotionValue(0);

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay asChild>
          <motion.div
            className="fixed inset-0 z-50 bg-black/50"
            initial={reduceMotion ? { opacity: 1 } : { opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduceMotion ? 0 : 0.24, ease: [0.32, 0.72, 0, 1] }}
          />
        </DialogPrimitive.Overlay>
        <DialogPrimitive.Content
          asChild
          aria-label={ariaLabel}
          onOpenAutoFocus={(e) => {
            // Prevent the default focus-the-first-focusable behaviour, which
            // can cause an iOS Safari keyboard pop on a buried <input>.
            e.preventDefault();
          }}
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            className={cn(
              "fixed inset-x-0 bottom-0 z-50 flex flex-col",
              "rounded-t-2xl bg-bg shadow-elevated",
              "border-t border-separator/40",
              fullHeight ? "h-[92dvh]" : "max-h-[92dvh]",
            )}
            style={{ y }}
            initial={reduceMotion ? { y: 0 } : { y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{
              type: "tween",
              ease: [0.32, 0.72, 0, 1],
              duration: reduceMotion ? 0 : 0.32,
            }}
            drag={dismissible && !reduceMotion ? "y" : false}
            dragConstraints={{ top: 0, bottom: 0 }}
            dragElastic={{ top: 0, bottom: 0.6 }}
            onDragEnd={(_event, info) => {
              if (!dismissible) return;
              if (
                info.offset.y > DRAG_DISMISS_THRESHOLD_PX ||
                info.velocity.y > DRAG_DISMISS_VELOCITY
              ) {
                onOpenChange(false);
              }
            }}
          >
            {dismissible && (
              <div
                className="flex select-none items-center justify-center pt-2 pb-1 cursor-grab active:cursor-grabbing"
                aria-hidden="true"
              >
                <span className="block h-[5px] w-9 rounded-full bg-label-quaternary/40" />
              </div>
            )}
            {children}
          </motion.div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/**
 * Top-bar inside a bottom sheet — short title centred, optional left + right.
 * Mirrors UINavigationBar inside UISheet.
 */
export function BottomSheetTopBar({
  title,
  left,
  right,
}: {
  title?: React.ReactNode;
  left?: React.ReactNode;
  right?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between px-4 pb-3 pt-1">
      <div className="flex min-w-[72px] items-center justify-start">
        {left}
      </div>
      <DialogPrimitive.Title asChild>
        <div className="text-headline text-label-primary truncate">{title}</div>
      </DialogPrimitive.Title>
      <div className="flex min-w-[72px] items-center justify-end">{right}</div>
    </div>
  );
}

/**
 * Scrollable body for a bottom sheet — handles overflow without bleeding into
 * the drag-handle / top-bar / sticky action-bar.
 */
export function BottomSheetBody({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex-1 overflow-y-auto overscroll-contain px-4 pb-6",
        className,
      )}
    >
      {children}
    </div>
  );
}

/**
 * Sticky action bar at the bottom of a sheet (e.g. Reject / Edit / Approve).
 * Sits above the home indicator via pb-safe.
 */
export function BottomSheetActionBar({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "shrink-0 border-t border-separator/40 bg-bg/95 backdrop-blur-md px-4 pt-3 pb-safe",
        className,
      )}
    >
      <div className="flex items-stretch gap-2 pb-3">{children}</div>
    </div>
  );
}
