"use client";

import * as React from "react";
import Link from "next/link";
import {
  AlertTriangle,
  CalendarDays,
  ChevronRight,
  Inbox,
  MailQuestion,
  RefreshCw,
  Sparkles,
  Truck,
  Workflow,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { ListRow } from "@/components/ui/list-row";
import { EmptyState } from "@/components/ui/empty-state";
import { useApprovals } from "@/lib/api";
import type { ApprovalItem, Lane } from "@/lib/schemas";
import { detectFlags } from "@/components/queue/FlagChips";

/**
 * /today — Daily Brief in-app view, per MOBILE_UX_SPEC §"Tab 2 — Today".
 *
 * No new endpoints — derives everything from useApprovals (the only data
 * source we have wired up today). Sections without data fall back to a
 * single-row "no items today" line; if the entire screen has no signal,
 * the spec calls for the "Quill builds your daily brief…" empty state.
 */

export default function TodayPage() {
  const { data, isLoading, dataUpdatedAt } = useApprovals();
  const qc = useQueryClient();
  const items = (data ?? []) as ApprovalItem[];

  const today = formatToday();

  const stats = computeStats(items);

  const isEmpty =
    !isLoading && items.length === 0;

  return (
    <MobileShell>
      <TopBar hero title="Today" subtitle={today} />

      <div className="bg-bg-elevated min-h-full">
        <div className="flex flex-col gap-4 px-4 pt-4 pb-8">
          {isEmpty ? (
            <EmptyState
              icon={<Sparkles />}
              title="No brief yet"
              subtitle="Quill builds your daily brief from agent activity. Check back tomorrow morning."
            />
          ) : (
            <>
              {/* Hero — Top of mind */}
              <TopOfMind topPriorityItems={stats.topPriority} />

              {/* Stacked sections */}
              <SectionCard
                icon={<Inbox className="h-4 w-4" />}
                title="Approvals waiting"
                href="/queue"
                value={`${stats.pending} pending`}
                subtitle={`Mandatory ${stats.byLane["tier-0-mandatory"]} · Spot-check ${stats.byLane["tier-1-spotcheck"]} · Auto ${stats.byLane["tier-2-auto"]}`}
              />

              <SectionCard
                icon={<AlertTriangle className="h-4 w-4" />}
                title="Critical path"
                href="/queue"
                value={
                  stats.criticalPath > 0
                    ? `${stats.criticalPath} flagged`
                    : "Clear"
                }
                subtitle={
                  stats.criticalPath > 0
                    ? "Items with critical-path or safety flags"
                    : "No items flagged for critical-path or safety"
                }
                tone={stats.criticalPath > 0 ? "danger" : "neutral"}
              />

              <SectionCard
                icon={<Truck className="h-4 w-4" />}
                title="Procurement watch"
                href="/queue"
                value={
                  stats.procurement > 0
                    ? `${stats.procurement} alert${stats.procurement > 1 ? "s" : ""}`
                    : "Clear"
                }
                subtitle={
                  stats.procurement > 0
                    ? "Long-lead PO or expediting items in queue"
                    : "No procurement alerts in queue"
                }
                tone={stats.procurement > 0 ? "warning" : "neutral"}
              />

              <SectionCard
                icon={<MailQuestion className="h-4 w-4" />}
                title="RFIs aged > 48h"
                href="/queue"
                value={
                  stats.rfiAged > 0
                    ? `${stats.rfiAged} aged`
                    : "On time"
                }
                subtitle={
                  stats.rfiAged > 0
                    ? "RFI-related items older than 48 hours"
                    : "No RFI items past 48-hour threshold"
                }
                tone={stats.rfiAged > 0 ? "warning" : "neutral"}
              />

              <SectionCard
                icon={<Workflow className="h-4 w-4" />}
                title="Hyperscaler inbox"
                href="/queue"
                value={
                  stats.hyperscaler > 0
                    ? `${stats.hyperscaler} item${stats.hyperscaler > 1 ? "s" : ""}`
                    : "Clear"
                }
                subtitle="Items addressed to hyperscaler liaison"
              />

              <SectionCard
                icon={<CalendarDays className="h-4 w-4" />}
                title="Today's calendar"
                href="/profile"
                value="—"
                subtitle="Not yet wired (calendar source pending)"
                disabled
              />
            </>
          )}
        </div>

        {/* Footer status */}
        <div className="px-4 pb-6 flex items-center justify-between text-footnote text-label-tertiary">
          <span>
            Last refreshed {formatLastRefreshed(dataUpdatedAt)}
          </span>
          <button
            type="button"
            onClick={() =>
              qc.invalidateQueries({ queryKey: ["approvals"] })
            }
            aria-label="Refresh"
            className="flex h-9 w-9 items-center justify-center text-accent active:opacity-60 no-tap-highlight"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>
      </div>
    </MobileShell>
  );
}

/* ── Hero card ─────────────────────────────────────────────────────────── */

function TopOfMind({ topPriorityItems }: { topPriorityItems: ApprovalItem[] }) {
  return (
    <section className="overflow-hidden rounded-xl bg-bg-tertiary p-4 shadow-card">
      <div className="flex items-center gap-2 mb-3">
        <Sparkles className="h-4 w-4 text-accent" />
        <h2 className="text-title-3 text-label-primary">Top of mind</h2>
      </div>
      {topPriorityItems.length === 0 ? (
        <p className="text-callout text-label-secondary">
          Nothing critical right now. Spot-check items are in /Queue.
        </p>
      ) : (
        <ul className="space-y-3">
          {topPriorityItems.slice(0, 3).map((item) => {
            const flags = detectFlags(item);
            return (
              <li key={item.approval_id}>
                <Link
                  href={`/queue`}
                  className="block no-tap-highlight active:opacity-70"
                >
                  <div className="text-headline text-label-primary line-clamp-1">
                    {item.summary ?? item.workflow}
                  </div>
                  <div className="text-callout text-label-secondary line-clamp-2">
                    {flags.length > 0
                      ? flags.map((f) => f.label).join(" · ")
                      : item.rationale ?? "Awaiting your decision"}
                  </div>
                  <div className="mt-1 text-footnote text-accent">
                    Review →
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/* ── Section card ──────────────────────────────────────────────────────── */

function SectionCard({
  icon,
  title,
  value,
  subtitle,
  href,
  tone = "neutral",
  disabled = false,
}: {
  icon: React.ReactNode;
  title: string;
  value: string;
  subtitle: string;
  href: string;
  tone?: "neutral" | "danger" | "warning";
  disabled?: boolean;
}) {
  const valueClass =
    tone === "danger"
      ? "text-danger"
      : tone === "warning"
        ? "text-warning"
        : "text-label-primary";

  const inner = (
    <div className="flex items-center gap-3 px-4 py-4 min-h-[68px]">
      <span
        className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md ${
          tone === "danger"
            ? "bg-danger/10 text-danger"
            : tone === "warning"
              ? "bg-warning/10 text-warning"
              : "bg-bg-elevated text-label-secondary"
        }`}
        aria-hidden="true"
      >
        {icon}
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-headline text-label-primary">{title}</div>
        <div className="text-callout text-label-secondary line-clamp-1">
          {subtitle}
        </div>
      </div>
      <div className="flex items-center gap-1">
        <span className={`text-callout font-medium tabular-nums ${valueClass}`}>
          {value}
        </span>
        {!disabled && (
          <ChevronRight className="h-4 w-4 text-label-quaternary" />
        )}
      </div>
    </div>
  );

  if (disabled) {
    return (
      <div className="overflow-hidden rounded-xl bg-bg-tertiary opacity-60 shadow-card">
        {inner}
      </div>
    );
  }
  return (
    <Link
      href={href}
      className="block overflow-hidden rounded-xl bg-bg-tertiary shadow-card no-tap-highlight active:bg-bg-elevated/60"
    >
      {inner}
    </Link>
  );
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

type Stats = {
  pending: number;
  byLane: Record<Lane, number>;
  topPriority: ApprovalItem[];
  criticalPath: number;
  procurement: number;
  rfiAged: number;
  hyperscaler: number;
};

function computeStats(items: ApprovalItem[]): Stats {
  const pending = items.filter((i) => i.status === "pending");

  const byLane: Record<Lane, number> = {
    "tier-0-mandatory": 0,
    "tier-1-spotcheck": 0,
    "tier-2-auto": 0,
  };
  for (const i of pending) {
    byLane[i.lane] = (byLane[i.lane] ?? 0) + 1;
  }

  // Top of mind: critical-path / safety-flagged or Lane 1 mandatory items.
  const flaggedDanger = pending.filter((i) => {
    const f = detectFlags(i);
    return f.some((x) => x.tone === "danger");
  });
  const mandatory = pending.filter((i) => i.lane === "tier-0-mandatory");
  const topPriority = uniqueById([...flaggedDanger, ...mandatory]).slice(0, 3);

  const criticalPath = pending.filter((i) => {
    const e = (i.escalations ?? []).map((x) => x.toLowerCase());
    return (
      e.includes("critical-path") ||
      e.includes("critical_path") ||
      e.includes("safety") ||
      e.includes("safety-impact")
    );
  }).length;

  const procurement = pending.filter((i) => {
    const w = i.workflow?.toLowerCase() ?? "";
    const a = i.agent_id?.toLowerCase() ?? "";
    const e = (i.escalations ?? []).map((x) => x.toLowerCase());
    return (
      w.includes("procurement") ||
      w.includes("po") ||
      a.includes("procurement") ||
      e.includes("long-lead")
    );
  }).length;

  const rfiAged = pending.filter((i) => {
    const isRfi =
      (i.workflow?.toLowerCase() ?? "").includes("rfi") ||
      (i.agent_id?.toLowerCase() ?? "").includes("rfi");
    if (!isRfi) return false;
    const age = Date.now() - +new Date(i.created_at);
    return age > 48 * 3_600_000;
  }).length;

  const hyperscaler = pending.filter((i) => {
    const w = i.workflow?.toLowerCase() ?? "";
    const a = i.agent_id?.toLowerCase() ?? "";
    return w.includes("hyperscaler") || a.includes("hyperscaler") || a.includes("liaison");
  }).length;

  return {
    pending: pending.length,
    byLane,
    topPriority,
    criticalPath,
    procurement,
    rfiAged,
    hyperscaler,
  };
}

function uniqueById(arr: ApprovalItem[]): ApprovalItem[] {
  const seen = new Set<string>();
  const out: ApprovalItem[] = [];
  for (const i of arr) {
    if (!seen.has(i.approval_id)) {
      seen.add(i.approval_id);
      out.push(i);
    }
  }
  return out;
}

function formatToday(): string {
  return new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    timeZone: "America/New_York",
  }).format(new Date());
}

function formatLastRefreshed(ts: number | undefined): string {
  if (!ts) return "just now";
  const seconds = Math.max(1, Math.floor((Date.now() - ts) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const mins = Math.floor(seconds / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  return `${hours}h ago`;
}
