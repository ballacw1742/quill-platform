"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Bot, Building2, Calculator, ClipboardList, DollarSign, FileText, FolderKanban, Inbox, MessageSquare, MoreHorizontal, Package, Sparkles, Terminal, TrendingUp, User, Users, X } from "lucide-react";
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
//
// Phase G.5: Estimates is its own first-class tab (slot 3) for the
// drawing-driven cost + schedule flow. We're now at the iOS HIG max of 5
// tabs; labels are kept short to render cleanly at 375px.
//
// Sprint DC.1: "Dev" tab added as 6th slot (between Documents and Profile).
// This deliberately exceeds Apple's HIG max of 5 tabs. Rationale: Quill is
// a power-user tool for Charles; the dev-chat surface is a core workflow.
// If the 6-tab layout proves problematic on smaller screens, the fix is to
// move "Dev" behind a "More" tab — tracked in KNOWN_ISSUES.md.
//
// Sprint Contracts.2: "Contracts" tab added as 5th slot (after Documents).
// This makes 7 tabs — two over Apple's HIG max of 5.
// KNOWN CAVEAT (visible-tolerable): On narrow screens (< 375px) tab labels
// Bottom-bar layout: 5 primary tabs visible at all times (Apple HIG max),
// less-frequent destinations consolidated under "More" which opens a sheet.
// Sprint DC.2: Sites + Projects replace Today/Queue/Estimates as primary tabs.
// Primary: Sites, Projects, Requests, Contracts + More
// More sheet: Today, Queue, Estimates, Dev, Documents, Profile, Approvals, Settings
const PRIMARY_TABS = [
  { href: "/sites", label: "Sites", icon: Building2 },
  { href: "/projects", label: "Projects", icon: FolderKanban },
  { href: "/requests", label: "Requests", icon: MessageSquare },
  { href: "/contracts", label: "Contracts", icon: ClipboardList },
  // The "More" button is the 5th slot rendered inline by TabBar.
] as const;

// Sprint DC.2: Today/Queue/Estimates moved to More sheet; Sites/Projects take primary.
const MORE_TABS = [
  { href: "/today", label: "Today", icon: Sparkles },
  { href: "/queue", label: "Queue", icon: Inbox },
  { href: "/estimates", label: "Estimates", icon: Calculator },
  { href: "/dev-chat", label: "Dev", icon: Terminal },
  { href: "/documents", label: "Documents", icon: FileText },
  { href: "/agents", label: "Agents", icon: Bot },  // Sprint DC.4 — Agent Registry
  { href: "/operations", label: "Operations", icon: Building2 },  // Sprint 1A — Facility Ops
  { href: "/pipeline", label: "Pipeline", icon: TrendingUp },  // Sprint 1B — Sales & Pipeline
  { href: "/customers", label: "Customers", icon: Users },  // Sprint 2A — Customer Success
  { href: "/supply-chain", label: "Supply Chain", icon: Package },  // Sprint 2B — Supply Chain
  { href: "/finance", label: "Finance", icon: DollarSign },  // Sprint 3A — Finance
  { href: "/profile", label: "Profile", icon: User },
] as const;

const MORE_HREFS = new Set<string>(MORE_TABS.map((t) => t.href));

// Legacy alias kept for any external imports.
const TABS = PRIMARY_TABS;

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

/* ── Bottom tab bar ─────────────────────────────────────────────────────── */

function TabBar() {
  const pathname = usePathname();
  const router = useRouter();
  const { data: approvals } = useApprovals();
  const pendingCount = approvals?.length ?? 0;
  const [moreOpen, setMoreOpen] = React.useState(false);

  const moreActive = Array.from(MORE_HREFS).some(
    (h) => pathname === h || pathname.startsWith(h + "/"),
  );

  const labelClass =
    "text-[10px] leading-[12px] font-medium tracking-tight";

  return (
    <>
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
        {PRIMARY_TABS.map(({ href, label, icon: Icon }) => {
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
                    className="h-6 w-6"
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
                <span className={cn(labelClass, "truncate max-w-full px-0.5")}>{label}</span>
              </Link>
            </li>
          );
        })}

        {/* More tab — 5th slot. Opens overflow sheet. */}
        <li className="flex-1">
          <button
            type="button"
            onClick={() => setMoreOpen(true)}
            role="tab"
            aria-selected={moreActive}
            aria-label="More"
            aria-haspopup="menu"
            aria-expanded={moreOpen}
            className={cn(
              "flex h-[49px] w-full flex-col items-center justify-center gap-0.5",
              "no-tap-highlight transition-state ease-ios",
              moreActive
                ? "text-accent"
                : "text-label-secondary active:text-accent",
            )}
          >
            <MoreHorizontal
              className="h-6 w-6"
              strokeWidth={moreActive ? 2 : 1.75}
              aria-hidden="true"
            />
            <span className={cn(labelClass, "truncate max-w-full px-0.5")}>More</span>
          </button>
        </li>
      </ul>
    </nav>

    {/* Overflow sheet — simple bottom drawer with the rest of the tabs. */}
    {moreOpen && (
      <>
        <div
          className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm"
          onClick={() => setMoreOpen(false)}
          aria-hidden="true"
        />
        <div
          role="menu"
          aria-label="More destinations"
          className={cn(
            "fixed bottom-0 left-0 right-0 z-50 bg-chrome",
            "rounded-t-2xl border-t border-separator/60 pb-safe",
            "shadow-[0_-12px_32px_-12px_rgba(0,0,0,0.32)]",
          )}
        >
          <div className="flex items-center justify-between px-4 pt-3 pb-2">
            <span className="text-headline font-semibold text-label-primary">
              More
            </span>
            <button
              type="button"
              onClick={() => setMoreOpen(false)}
              aria-label="Close"
              className="flex h-9 w-9 items-center justify-center rounded-full bg-bg-elevated text-label-secondary active:opacity-70 no-tap-highlight"
            >
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
          </div>
          <ul className="flex flex-col px-2 pb-3">
            {MORE_TABS.map(({ href, label, icon: Icon }) => {
              const active =
                pathname === href || pathname.startsWith(href + "/");
              return (
                <li key={href}>
                  <button
                    type="button"
                    onClick={() => {
                      setMoreOpen(false);
                      router.push(href);
                    }}
                    role="menuitem"
                    className={cn(
                      "flex w-full items-center gap-3 rounded-xl px-4 py-3",
                      "min-h-[56px] no-tap-highlight active:bg-bg-elevated",
                      active ? "text-accent" : "text-label-primary",
                    )}
                  >
                    <span
                      className={cn(
                        "flex h-9 w-9 items-center justify-center rounded-xl",
                        active
                          ? "bg-accent/10 text-accent"
                          : "bg-bg-elevated text-label-secondary",
                      )}
                    >
                      <Icon className="h-5 w-5" strokeWidth={active ? 2 : 1.75} />
                    </span>
                    <span className="text-body font-medium">{label}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      </>
    )}
    </>
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
