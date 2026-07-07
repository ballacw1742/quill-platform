"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Activity,
  BellRing,
  Bot,
  ClipboardCheck,
  LogOut,
  ScrollText,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useApprovalsSocket } from "@/lib/websocket";
import { useApprovals, useLogout, useSession } from "@/lib/api";
import type { Session } from "@/lib/schemas";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";

const NAV = [
  { href: "/queue", label: "Queue", icon: ClipboardCheck },
  { href: "/audit", label: "Activity", icon: ScrollText },
  { href: "/agents", label: "Agents", icon: Bot },
  { href: "/assistant", label: "Assistant", icon: Sparkles },
  { href: "/health", label: "Health", icon: Activity },
];

export function AppShell({
  children,
  search,
  onSearchChange,
}: {
  children: React.ReactNode;
  search?: string;
  onSearchChange?: (v: string) => void;
}) {
  useApprovalsSocket();
  const pathname = usePathname();
  const router = useRouter();
  const { data: rawSession, isLoading } = useSession();
  const session = rawSession as Session | null | undefined;
  const logout = useLogout();
  const { data: approvals } = useApprovals();
  const pendingCount = approvals?.length ?? 0;

  React.useEffect(() => {
    if (isLoading) return;
    if (!session) router.replace("/login");
  }, [isLoading, session, router]);

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-40 border-b bg-background/95 backdrop-blur">
        <div className="flex h-14 items-center gap-3 px-3 md:px-6">
          <Link href="/queue" className="flex items-center gap-2 font-semibold">
            <ShieldCheck className="h-5 w-5 text-primary" />
            <span className="hidden sm:inline">Quill</span>
          </Link>
          <nav className="ml-2 hidden items-center gap-1 md:flex">
            {NAV.map(({ href, label, icon: Icon }) => {
              const active = pathname === href || pathname.startsWith(href + "/");
              return (
                <Link
                  key={href}
                  href={href}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                    active ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-accent",
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {label}
                  {href === "/queue" && pendingCount > 0 && (
                    <Badge variant="secondary" className="ml-1 h-5 px-1.5 text-[10px]">
                      {pendingCount}
                    </Badge>
                  )}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            {onSearchChange && (
              <div className="relative hidden md:block">
                <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={search ?? ""}
                  onChange={(e) => onSearchChange(e.target.value)}
                  placeholder="Search approvals…"
                  className="h-9 w-64 pl-8"
                />
              </div>
            )}
            <Button variant="ghost" size="icon" aria-label="Notifications" className="relative">
              <BellRing className="h-4 w-4" />
              {pendingCount > 0 && (
                <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-destructive" />
              )}
            </Button>
            <Sheet>
              <SheetTrigger asChild>
                <Button variant="outline" size="sm" className="hidden sm:inline-flex">
                  {session?.display_name?.split(" ")[0] ?? "Account"}
                </Button>
              </SheetTrigger>
              <SheetContent side="right">
                <SheetHeader>
                  <SheetTitle>Account</SheetTitle>
                </SheetHeader>
                <div className="mt-4 space-y-2 text-sm">
                  <div>
                    <div className="text-muted-foreground">Signed in as</div>
                    <div className="font-medium">{session?.display_name ?? "—"}</div>
                    <div className="text-xs text-muted-foreground">{session?.email}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground">Role</div>
                    <Badge variant="secondary">{session?.role ?? "viewer"}</Badge>
                  </div>
                  <Button
                    variant="outline"
                    className="mt-4 w-full"
                    onClick={() => {
                      logout.mutate(undefined, { onSuccess: () => router.replace("/login") });
                    }}
                  >
                    <LogOut className="h-4 w-4" /> Sign out
                  </Button>
                </div>
              </SheetContent>
            </Sheet>
          </div>
        </div>
        <nav className="flex items-center gap-1 overflow-x-auto border-t px-2 py-1 md:hidden">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || pathname.startsWith(href + "/");
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium",
                  active ? "bg-secondary text-foreground" : "text-muted-foreground",
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </Link>
            );
          })}
        </nav>
      </header>
      <main className="flex-1">{children}</main>
    </div>
  );
}
