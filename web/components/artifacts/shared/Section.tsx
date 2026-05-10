"use client";

import * as React from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Section — collapsible section with iOS-style header.
 * In print mode all sections are forced open.
 */
export function Section({
  title,
  defaultOpen = true,
  printForceOpen = false,
  className,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  printForceOpen?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(defaultOpen);
  const isOpen = printForceOpen ? true : open;

  return (
    <div className={cn("rounded-xl bg-bg-elevated overflow-hidden", className)}>
      <button
        type="button"
        onClick={() => !printForceOpen && setOpen((v) => !v)}
        aria-expanded={isOpen}
        className={cn(
          "flex w-full items-center justify-between px-4 py-3 min-h-[44px]",
          !printForceOpen && "active:bg-bg-tertiary/40 no-tap-highlight",
          "print:cursor-default",
        )}
      >
        <span className="text-callout text-label-primary font-semibold">
          {title}
        </span>
        {!printForceOpen && (
          <ChevronDown
            className={cn(
              "h-4 w-4 text-label-tertiary transition-transform print:hidden",
              isOpen && "rotate-180",
            )}
            aria-hidden="true"
          />
        )}
      </button>
      {isOpen && (
        <div className="px-4 pb-4">
          {children}
        </div>
      )}
    </div>
  );
}
