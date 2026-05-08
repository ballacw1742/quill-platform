"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { FileText, Inbox, Sparkles, User } from "lucide-react";
import { cn } from "@/lib/utils";
import { useApprovalsSocket } from "@/lib/websocket";
import { useApprovals, useSession } from "@/lib/api";
import type { Session } from "@/lib/schemas";

/**
 * MobileShell — the iOS-redesign authenticated app shell.
 *
 * Replaces the desktop AppShell (top bar + drawer + 4-link nav) with a
 * mobile-first layout per DESIGN_SYSTEM.md §7 + MOBILE_UX_SPEC.md "App shell":
 *
 *   ┌────────────────────────────────────┐
 *   │  Top bar (per-screen, dynamic)     │  44 px + safe-top
 *   ├────────────────────────────────────┤
 *   │                                    │
 *   │  Page content                      │  flex-1, scrollable
 *   │                                    │
 *   ├────────────────────────────────────┤
 *   │  Tab bar (4 tabs, frosted glass)   │  49 px + safe-bottom
 *   └────────────────────────────────────┘
 *
 * Each route owns its own top bar (we expose `<TopBar>` here as a co-loc
 * primitive). The shell is responsible for: auth gating, the tab bar, the
 * scroll container, and pb-tab-bar so content never sits under the bar.
 *
 * Desktop (md+) still uses the bottom tab bar in this sprint to keep the
 * surface consistent. A real left-rail sidebar is a future-sprint concern
 * called out in MOBILE_UX_SPEC §7.
 */

// Phase D.2: Documents replaces Activity in the bottom bar; Activity moves
// under Profile (DOCUMENTS_SPEC.md §"Tab bar update"). The existing /audit
// route is preserved — it's now reached via Profile → Activity.
const TABS = [
  { href: "/queue", label: "Queue", icon: Inbox },
  { href: "/today", label: "Today", icon: Sparkles },
  { href: "/documents", label: "Documents", icon: FileText },
  { href: "/profile", label: "Profile", icon: User },
] as const;

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
  const { data: rawSession, isLoading } = useSession();
  const session = rawSession as Session | null | undefined;

  React.useEffect(() => {
    if (!requireAuth) return;
    if (isLoading) return;
    if (!session) router.replace("/login");
  }, [requireAuth, isLoading, session, router]);

  return (
    <div className="flex min-h-screen flex-col bg-bg">
      <main className="flex-1 pb-tab-bar">{children}</main>
      <TabBar />
    </div>
  );
}

/* ── Top bar ─────────────────────────────────────────────────────────────── */

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
  left,
  right,
  className,
}: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  hero?: boolean;
  left?: React.ReactNode;
  right?: React.ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "sticky top-0 z-30 pt-safe bg-chrome",
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
        <div className="flex w-12 items-center justify-start">{left}</div>
        <div className="flex flex-1 items-center justify-center min-w-0">
          {!hero && title && (
            <span className="truncate text-headline text-label-primary">
              {title}
            </span>
          )}
        </div>
        <div className="flex w-12 items-center justify-end">{right}</div>
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

/* ── Bottom tab bar ─────────────────────────────────────────────────────── */

function TabBar() {
  const pathname = usePathname();
  const { data: approvals } = useApprovals();
  const pendingCount = approvals?.length ?? 0;

  return (
    <nav
      className={cn(
        "fixed bottom-0 left-0 right-0 z-40 bg-chrome",
        "border-t border-separator/60",
        "pb-safe",
      )}
      role="tablist"
      aria-label="Primary"
    >
      <ul className="flex items-stretch justify-around px-2">
        {TABS.map(({ href, label, icon: Icon }) => {
          const active =
            pathname === href ||
            pathname.startsWith(href + "/") ||
            // /approvals/* is conceptually under /queue
            (href === "/queue" && pathname.startsWith("/approvals")) ||
            // /audit is reached via Profile → Activity (per Phase D.2 tab
            // bar update), so highlight Profile when the user is in /audit.
            (href === "/profile" && pathname.startsWith("/audit"));
          const showBadge = href === "/queue" && pendingCount > 0;
          return (
            <li key={href} className="flex-1">
              <Link
                href={href}
                role="tab"
                aria-selected={active}
                aria-label={label}
                className={cn(
                  "flex h-[49px] flex-col items-center justify-center gap-0.5",
                  "no-tap-highlight transition-state ease-ios",
                  active
                    ? "text-accent"
                    : "text-label-secondary active:text-accent",
                )}
              >
                <span className="relative inline-flex">
                  <Icon
                    className="h-7 w-7"
                    strokeWidth={active ? 2 : 1.75}
                    aria-hidden="true"
                  />
                  {showBadge && (
                    <span
                      className="absolute -right-1.5 -top-0.5 inline-flex min-w-[16px] items-center justify-center rounded-full bg-danger px-1 text-caption-2 font-semibold text-white"
                      aria-label={`${pendingCount} pending`}
                    >
                      {pendingCount > 99 ? "99+" : pendingCount}
                    </span>
                  )}
                </span>
                <span className="text-caption-2 font-medium">{label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/* ── Top-bar building blocks ─────────────────────────────────────────────── */

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
      className="-ml-2 flex min-h-[44px] min-w-[44px] items-center gap-1 rounded-md px-2 text-accent active:opacity-60 no-tap-highlight"
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
      <span className="text-body">{label}</span>
    </button>
  );
}
