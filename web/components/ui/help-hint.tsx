"use client";

import * as React from "react";
import { HelpCircle } from "lucide-react";
import {
  BottomSheet,
  BottomSheetBody,
  BottomSheetTopBar,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { getHelp } from "@/lib/help-content";

/**
 * HelpHint — a small inline `?` icon that opens a bottom sheet with a
 * 1–2 paragraph plain-English explanation of a UI term.
 *
 * Per COPY_GUIDE.md §"Inline help":
 *   - 16px lucide HelpCircle, label-tertiary color
 *   - Tap → bottom sheet with title + short body
 *   - Hit target meets the 44px iOS minimum (transparent padding)
 *
 * Usage:
 *     <HelpHint term="lane" />
 *
 * The `term` prop is a key into the HELP_CONTENT dictionary in
 * `lib/help-content.ts`.
 */
export function HelpHint({
  term,
  iconClassName,
  ariaLabel,
}: {
  term: string;
  iconClassName?: string;
  ariaLabel?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const help = getHelp(term);
  return (
    <>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
        aria-label={ariaLabel ?? `What is ${term.replace(/_/g, " ")}?`}
        className={cn(
          // 44px hit target via padding; visible glyph stays 16px.
          "inline-flex h-11 w-11 items-center justify-center -m-3 align-middle",
          "text-label-tertiary active:opacity-60 no-tap-highlight",
        )}
      >
        <HelpCircle
          className={cn("h-4 w-4", iconClassName)}
          aria-hidden="true"
        />
      </button>
      <BottomSheet
        open={open}
        onOpenChange={setOpen}
        ariaLabel={help.title}
      >
        <BottomSheetTopBar
          title={help.title}
          right={
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="text-body text-accent active:opacity-60 no-tap-highlight min-h-[44px] -mr-2 px-2"
            >
              Done
            </button>
          }
        />
        <BottomSheetBody>
          <div className="space-y-3 pb-6">
            {help.body.map((p, i) => (
              <p
                key={i}
                className="text-body text-label-primary leading-relaxed"
              >
                {p}
              </p>
            ))}
          </div>
        </BottomSheetBody>
      </BottomSheet>
    </>
  );
}
