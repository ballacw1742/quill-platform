"use client";

import * as React from "react";
import { usePathname, useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { useApprovalsSocket } from "@/lib/websocket";
import { useSession } from "@/lib/api";
import { FloatingHomeButton } from "@/components/layout/FloatingHomeButton";
import type { Session } from "@/lib/schemas";

/**
 * MobileShell — the iOS-redesign authenticated app shell.
 *
 * UI redesign (docs/UI_REDESIGN_BRIEF.md): the bottom tab bar + "More"
 * sheet are gone. Navigation is now the iOS home-screen model:
 *
 *   ┌────────────────────────────────────┐
 *   │  Top bar (per-screen, dynamic)     │  44 px + safe-top
 *   ├────────────────────────────────────┤
 *   │  Page content                      │  flex-1, scrollable
 *   │                        ○ Home     │  floating Liquid Glass button
 *   └────────────────────────────────────┘
 *
 * The shell is responsible for: auth gating, the scroll container with
 * `pb-home` bottom inset (no-overlap guarantee for the floating button),
 * and rendering the FloatingHomeButton on every non-home route. Each route
 * still owns its own top bar via `<TopBar>`.
 */
export function MobileShell({
  children,
  requireAuth = true,
}: {
  children: React.ReactNode;
  requireAuth?: boolean;
}) {
  // Subscribe to approvals socket so live updates flow even when the
  // /queue page isn't currently mounted (e.g. when the user is on /today).
  useApprovalsSocket();

  const router = useRouter();
  const pathname = usePathname();
  const { data: rawSession, isLoading } = useSession();
  const session = rawSession as Session | null | undefined;

  React.useEffect(() => {
    if (!requireAuth) return;
    if (isLoading) return;
    if (!session) router.replace("/login");
  }, [requireAuth, isLoading, session, router]);

  const isHome = pathname === "/";

  return (
    <div className="flex min-h-screen flex-col bg-bg">
      <main className={cn("flex-1", isHome ? "pb-safe" : "pb-home")}>
        {children}
      </main>
      {!isHome && <FloatingHomeButton />}
    </div>
  );
}

/* ── Top bar ─────────────────────────────────────────────────────── */

/**
 * TopBar — per-screen top bar, sized like UINavigationBar (44 px + safe-top).
 *
 * Variants:
 * - default: title left-aligned (text-headline), optional left-back, right-action
 * - hero:    title in text-large-title with optional subtitle; used on /today
 *            and /profile root.
 *
 * Apple's pattern is the bar background matches the page bg until content
 * scrolls under it, at which point a hairline separator appears. We approximate
 * with a chrome-blur applied unconditionally — looks correct in both states.
 */
export function TopBar({
  title,
  subtitle,
  hero = false,
  sticky = true,
  left,
  right,
  className,
}: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  hero?: boolean;
  /** Set false on long scroll pages where a pinned hero would sit over content (iOS large titles scroll away). */
  sticky?: boolean;
  left?: React.ReactNode;
  right?: React.ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        sticky ? "sticky top-0 z-30 bg-chrome" : "relative",
        "pt-safe",
        hero ? "border-0" : "border-b border-separator/40",
        className,
      )}
    >
      <div
        className={cn(
          "flex items-center px-4",
          hero ? "min-h-[64px] pb-2 pt-3" : "min-h-[44px]",
        )}
      >
        <div className="flex shrink-0 max-w-[40%] items-center justify-start min-w-[44px] overflow-hidden">
          {left}
        </div>
        <div className="flex flex-1 items-center justify-center min-w-0 px-2">
          {!hero && title && (
            <span className="truncate text-headline text-label-primary text-center">
              {title}
            </span>
          )}
        </div>
        <div className="flex shrink-0 max-w-[40%] items-center justify-end min-w-[44px] overflow-hidden">
          {right}
        </div>
      </div>
      {hero && (title || subtitle) && (
        <div className="px-4 pb-3">
          {title && (
            <h1 className="text-large-title text-label-primary">{title}</h1>
          )}
          {subtitle && (
            <div className="mt-0.5 text-headline text-label-secondary">
              {subtitle}
            </div>
          )}
        </div>
      )}
    </header>
  );
}

/* ── Top-bar building blocks ─────────────────────────────────────────── */

/**
 * Back-chevron button. iOS uses a thin chevron + the previous screen's title;
 * we use the chevron + an optional label since we don't have the navigation
 * stack from React Router.
 */
export function BackButton({
  href,
  onClick,
  label = "Back",
}: {
  href?: string;
  onClick?: () => void;
  label?: string;
}) {
  const router = useRouter();
  const handleClick = () => {
    if (onClick) return onClick();
    if (href) return router.push(href);
    router.back();
  };
  return (
    <button
      type="button"
      onClick={handleClick}
      aria-label={label}
      className="-ml-2 flex min-h-[44px] min-w-[44px] max-w-full items-center gap-1 rounded-md px-2 text-accent active:opacity-60 no-tap-highlight"
    >
      <svg
        viewBox="0 0 12 22"
        className="h-[18px] w-[10px]"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <polyline points="11,2 2,11 11,20" />
      </svg>
      <span className="text-body truncate">{label}</span>
    </button>
  );
}
