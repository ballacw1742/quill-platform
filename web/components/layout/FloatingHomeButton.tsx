"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Home } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * FloatingHomeButton — 56px circular Liquid Glass button, fixed
 * bottom-center above the safe area (UI_REDESIGN_BRIEF §4).
 *
 * Rendered globally by MobileShell on every non-home route; hidden on the
 * home screen itself. Press = spring scale to 0.96, navigates to `/`.
 * Pages reserve space for it via the `pb-home` utility so it never covers
 * content (no-overlap guarantee).
 */
export function FloatingHomeButton({ className }: { className?: string }) {
  const router = useRouter();
  const [pressed, setPressed] = React.useState(false);

  return (
    <button
      type="button"
      aria-label="Go to Home"
      onClick={() => router.push("/")}
      onPointerDown={() => setPressed(true)}
      onPointerUp={() => setPressed(false)}
      onPointerLeave={() => setPressed(false)}
      onPointerCancel={() => setPressed(false)}
      className={cn(
        "glass fixed left-1/2 z-40 -translate-x-1/2",
        "bottom-[calc(env(safe-area-inset-bottom,0px)+16px)]",
        "flex h-14 w-14 items-center justify-center rounded-full",
        "text-label-primary no-tap-highlight",
        "transition-transform duration-tap ease-ios",
        pressed ? "scale-[0.96]" : "scale-100",
        className,
      )}
    >
      <Home className="h-6 w-6" strokeWidth={1.9} aria-hidden="true" />
    </button>
  );
}
