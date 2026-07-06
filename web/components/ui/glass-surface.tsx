import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * GlassSurface — Liquid Glass material primitive (UI_REDESIGN_BRIEF §2).
 *
 * Translucent background + backdrop blur + hairline border + soft shadow,
 * adapting to light/dark via the --bg-translucent / --separator tokens
 * (see .glass / .glass-strong in globals.css).
 */
export function GlassSurface({
  strong = false,
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { strong?: boolean }) {
  return (
    <div className={cn(strong ? "glass-strong" : "glass", className)} {...props}>
      {children}
    </div>
  );
}
