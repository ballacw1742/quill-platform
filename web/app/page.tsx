"use client";

/**
 * / — iOS-style Home Screen (UI_REDESIGN_BRIEF §3, decisions locked §9).
 *
 * Layout, top to bottom:
 *  - Greeting header ("Good morning, {name}") + date; avatar top-right opens
 *    a sheet with Profile / Settings / Dev Chat / Sign out.
 *  - Compact Today strip: pending approvals + open requests, tappable.
 *  - 3×5 grid of 15 squircle ModuleTiles (roster locked in brief §9.1).
 *
 * Auth-gated like every other page (MobileShell redirects to /login).
 * The FloatingHomeButton is hidden here (MobileShell hides it on "/").
 */

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Bot,
  Brain,
  Calculator,
  CheckCircle2,
  ClipboardList,
  DollarSign,
  Factory,
  FileText,
  FolderKanban,
  Inbox,
  LogOut,
  MapPin,
  MessageSquare,
  Package,
  Settings,
  Shield,
  Terminal,
  TrendingUp,
  User,
  Users,
  X,
} from "lucide-react";
import { MobileShell } from "@/components/layout/MobileShell";
import { ModuleTile } from "@/components/home/ModuleTile";
import { useApprovals, useLogout, useProjectRequests, useSession } from "@/lib/api";
import type { Session } from "@/lib/schemas";
import { cn } from "@/lib/utils";

/* ── Module roster — exactly 15 tiles, order locked (brief §3) ─────────── */
const MODULES = [
  { href: "/requests", label: "Requests", icon: MessageSquare, gradient: "from-indigo-400 to-indigo-600" },
  { href: "/queue", label: "Approvals", icon: Inbox, gradient: "from-red-400 to-rose-600", badge: "approvals" as const },
  { href: "/projects", label: "Projects", icon: FolderKanban, gradient: "from-sky-400 to-blue-600" },
  { href: "/sites", label: "Sites", icon: MapPin, gradient: "from-emerald-400 to-green-600" },
  { href: "/contracts", label: "Contracts", icon: ClipboardList, gradient: "from-amber-400 to-orange-600" },
  { href: "/estimates", label: "Estimates", icon: Calculator, gradient: "from-teal-400 to-cyan-600" },
  { href: "/documents", label: "Documents", icon: FileText, gradient: "from-slate-400 to-slate-600" },
  { href: "/operations", label: "Operations", icon: Factory, gradient: "from-orange-400 to-red-500" },
  { href: "/pipeline", label: "Sales", icon: TrendingUp, gradient: "from-fuchsia-400 to-purple-600" },
  { href: "/customers", label: "Customers", icon: Users, gradient: "from-pink-400 to-rose-500" },
  { href: "/supply-chain", label: "Supply Chain", icon: Package, gradient: "from-lime-500 to-emerald-600" },
  { href: "/finance", label: "Finance", icon: DollarSign, gradient: "from-green-500 to-emerald-700" },
  { href: "/compliance", label: "Compliance", icon: Shield, gradient: "from-blue-500 to-indigo-700" },
  { href: "/intelligence", label: "Intelligence", icon: Brain, gradient: "from-violet-400 to-purple-700" },
  { href: "/agents", label: "Agents", icon: Bot, gradient: "from-cyan-500 to-sky-700" },
];

function greetingFor(hour: number): string {
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

export default function HomePage() {
  return (
    <MobileShell>
      <HomeScreen />
    </MobileShell>
  );
}

function HomeScreen() {
  const { data: rawSession } = useSession();
  const session = rawSession as Session | null | undefined;
  const { data: approvals } = useApprovals();
  const { data: requestsData } = useProjectRequests();

  const pendingApprovals = (approvals ?? []).filter((a) => a.status === "pending").length;
  const openRequests = (requestsData?.items ?? []).filter((r) => r.status === "processing").length;

  const [now, setNow] = React.useState<Date | null>(null);
  React.useEffect(() => setNow(new Date()), []);

  const firstName =
    session?.display_name?.split(" ")[0] ||
    session?.email?.split("@")[0] ||
    "there";

  const dateLabel = now
    ? now.toLocaleDateString("en-US", {
        weekday: "long",
        month: "long",
        day: "numeric",
        timeZone: "America/New_York",
      })
    : "";

  return (
    <div className="mx-auto w-full max-w-[708px] px-5 pt-safe">
      {/* ── Greeting header ── */}
      <header className="flex items-start justify-between pt-6 pb-4">
        <div className="min-w-0">
          <p className="text-footnote font-medium uppercase tracking-wide text-label-secondary/60">
            {dateLabel || "\u00A0"}
          </p>
          <h1 className="mt-0.5 text-large-title text-label-primary">
            {now ? greetingFor(now.getHours()) : "Hello"}, {firstName}
          </h1>
        </div>
        <AvatarMenu session={session} />
      </header>

      {/* ── Today strip ── */}
      <section aria-label="Today" className="mb-6 grid grid-cols-2 gap-3">
        <Link
          href="/queue"
          className="glass flex items-center gap-3 rounded-2xl px-4 py-3 no-tap-highlight active:opacity-70 transition-state ease-ios"
        >
          <CheckCircle2 className="h-6 w-6 shrink-0 text-accent" aria-hidden="true" />
          <span className="min-w-0">
            <span className="block text-title-3 leading-6 text-label-primary">{pendingApprovals}</span>
            <span className="block text-footnote text-label-secondary">Pending approvals</span>
          </span>
        </Link>
        <Link
          href="/today"
          className="glass flex items-center gap-3 rounded-2xl px-4 py-3 no-tap-highlight active:opacity-70 transition-state ease-ios"
        >
          <MessageSquare className="h-6 w-6 shrink-0 text-accent" aria-hidden="true" />
          <span className="min-w-0">
            <span className="block text-title-3 leading-6 text-label-primary">{openRequests}</span>
            <span className="block text-footnote text-label-secondary">Open requests</span>
          </span>
        </Link>
      </section>

      {/* ── 3×5 module grid ── */}
      <section aria-label="Modules" className="grid grid-cols-3 gap-x-4 gap-y-6 pb-8 sm:gap-x-8">
        {MODULES.map((m) => (
          <ModuleTile
            key={m.href}
            href={m.href}
            label={m.label}
            icon={m.icon}
            gradient={m.gradient}
            badge={m.badge === "approvals" ? pendingApprovals : undefined}
          />
        ))}
      </section>
    </div>
  );
}

/* ── Avatar + account sheet ────────────────────────────────────────────── */
function AvatarMenu({ session }: { session: Session | null | undefined }) {
  const [open, setOpen] = React.useState(false);
  const router = useRouter();
  const logout = useLogout();

  const initials = (session?.display_name || session?.email || "?")
    .split(" ")
    .map((s) => s[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  const items = [
    { label: "Profile", icon: User, onSelect: () => router.push("/profile") },
    { label: "Settings", icon: Settings, onSelect: () => router.push("/settings") },
    { label: "Dev Chat", icon: Terminal, onSelect: () => router.push("/dev-chat") },
    {
      label: "Sign out",
      icon: LogOut,
      destructive: true,
      onSelect: () =>
        logout.mutate(undefined, { onSuccess: () => router.replace("/login") }),
    },
  ];

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Account menu"
        aria-haspopup="menu"
        aria-expanded={open}
        className="mt-1 flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-accent text-callout font-semibold text-white no-tap-highlight active:opacity-80 transition-state ease-ios"
      >
        {initials}
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <div
            role="menu"
            aria-label="Account"
            className="glass-strong fixed bottom-0 left-0 right-0 z-50 rounded-t-2xl pb-safe animate-sheet-in"
          >
            <div className="flex items-center justify-between px-4 pt-3 pb-2">
              <div className="min-w-0">
                <p className="truncate text-headline text-label-primary">
                  {session?.display_name || "Account"}
                </p>
                {session?.email && (
                  <p className="truncate text-footnote text-label-secondary">{session.email}</p>
                )}
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close"
                className="flex h-9 w-9 items-center justify-center rounded-full bg-bg-elevated text-label-secondary active:opacity-70 no-tap-highlight"
              >
                <X className="h-5 w-5" aria-hidden="true" />
              </button>
            </div>
            <ul className="flex flex-col px-2 pb-3">
              {items.map(({ label, icon: Icon, onSelect, destructive }) => (
                <li key={label}>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setOpen(false);
                      onSelect();
                    }}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-xl px-4 py-3 min-h-[52px]",
                      "no-tap-highlight active:bg-bg-elevated",
                      destructive ? "text-danger" : "text-label-primary",
                    )}
                  >
                    <Icon className="h-5 w-5" strokeWidth={1.8} aria-hidden="true" />
                    <span className="text-body font-medium">{label}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </>
  );
}
