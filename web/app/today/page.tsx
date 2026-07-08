"use client";

import * as React from "react";
import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  FolderKanban,
  Package,
  RefreshCw,
  Sparkles,
  TrendingUp,
  Users,
  Building2,
  Zap,
  MapPin,
  Workflow,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { SkelSectionCard } from "@/components/ui/skeletons";
import { ApprovalDetailSheet } from "@/components/queue/ApprovalDetailSheet";
import { SectionCard } from "@/components/today/SectionCard";
import { NeedsSignoffRow } from "@/components/today/NeedsSignoffRow";
import { InFlightRow } from "@/components/today/InFlightRow";
import { RecentItemRow } from "@/components/today/RecentItemRow";
import { NeedsAttentionRow } from "@/components/today/NeedsAttentionRow";
import {
  useApprovals,
  useListEstimates,
  useContractsList,
  useKpis,
  useExceptions,
  useSession,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ApprovalItem } from "@/lib/schemas";
import type { ContractListItem } from "@/lib/schemas";
import type { EstimateListItem } from "@/lib/api";
import type { KpiSnapshot, ExceptionItem } from "@/lib/schemas";
import {
  deriveNeedsSignoff,
  deriveInFlight,
  deriveRecentlyShipped,
  deriveNeedsAttention,
  countPendingApprovals,
} from "@/lib/today";

/* ── Quick links definition ───────────────────────────────────────────────── */

const QUICK_LINKS = [
  { href: "/lifecycle", label: "Lifecycle", icon: Workflow },
  { href: "/sites", label: "Sites", icon: MapPin },
  { href: "/projects", label: "Projects", icon: FolderKanban },
  { href: "/operations", label: "Operations", icon: Building2 },
  { href: "/pipeline", label: "Pipeline", icon: TrendingUp },
  { href: "/customers", label: "Customers", icon: Users },
  { href: "/supply-chain", label: "Supply Chain", icon: Package },
] as const;

/* ── Severity styling ────────────────────────────────────────────────────── */

function severityBadgeClass(severity: string) {
  switch (severity) {
    case "P1":
      return "bg-danger text-white";
    case "P2":
      return "bg-orange-500 text-white";
    case "WARNING":
      return "bg-yellow-500 text-white";
    default:
      return "bg-bg-elevated text-label-secondary";
  }
}

function moduleTagClass(module: string) {
  switch (module) {
    case "OPERATIONS":
      return "bg-blue-500/10 text-blue-600";
    case "SALES":
      return "bg-green-500/10 text-green-700";
    case "SUPPLY CHAIN":
      return "bg-orange-500/10 text-orange-700";
    case "FINANCE":
      return "bg-purple-500/10 text-purple-700";
    case "CUSTOMERS":
      return "bg-teal-500/10 text-teal-700";
    case "SITES":
      return "bg-indigo-500/10 text-indigo-700";
    case "PROJECTS":
      return "bg-cyan-500/10 text-cyan-700";
    default:
      return "bg-bg-elevated text-label-secondary";
  }
}

/* ── KPI card component ──────────────────────────────────────────────────── */

function KpiCard({
  label,
  value,
  unit,
  colorClass,
}: {
  label: string;
  value: string;
  unit?: string;
  colorClass?: string;
}) {
  return (
    <div className="flex-shrink-0 w-36 rounded-xl bg-bg-elevated px-4 py-3 flex flex-col gap-1">
      <span className="text-caption-1 text-label-tertiary truncate">{label}</span>
      <span className={cn("text-title-2 font-semibold tabular-nums", colorClass ?? "text-label-primary")}>
        {value}
      </span>
      {unit && (
        <span className="text-caption-2 text-label-quaternary">{unit}</span>
      )}
    </div>
  );
}

/* ── Exception row ───────────────────────────────────────────────────────── */

function ExceptionRow({ item }: { item: ExceptionItem }) {
  const relTime = formatRelTime(item.created_at);
  return (
    <div className="flex items-start gap-3 py-3 border-b border-separator/30 last:border-0">
      <span
        className={cn(
          "mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-caption-2 font-semibold uppercase tracking-wide",
          severityBadgeClass(item.severity),
        )}
      >
        {item.severity}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className={cn(
              "rounded px-1.5 py-0.5 text-caption-2 font-medium uppercase tracking-wide",
              moduleTagClass(item.module),
            )}
          >
            {item.module}
          </span>
          <span className="text-caption-1 text-label-quaternary">{relTime}</span>
        </div>
        <p className="mt-1 text-footnote text-label-primary leading-snug">{item.description}</p>
      </div>
    </div>
  );
}

/* ── Main page ───────────────────────────────────────────────────────────── */

export default function TodayPage() {
  const qc = useQueryClient();

  // ── Session ───────────────────────────────────────────────────────────────
  const { data: rawSession } = useSession();
  const displayName = (rawSession as any)?.display_name ?? (rawSession as any)?.email ?? "";

  // ── Intelligence data ─────────────────────────────────────────────────────
  const kpisQuery = useKpis();
  const exceptionsQuery = useExceptions();

  const kpis = kpisQuery.data as KpiSnapshot | undefined;
  const exceptions: ExceptionItem[] = exceptionsQuery.data?.items ?? [];

  // ── Legacy approval-queue data ────────────────────────────────────────────
  const approvalsQuery = useApprovals();
  const estimatesQuery = useListEstimates();
  const contractsQuery = useContractsList({ limit: 100 });

  const approvals = React.useMemo<ApprovalItem[]>(
    () => approvalsQuery.data ?? [],
    [approvalsQuery.data],
  );
  const estimates = React.useMemo<EstimateListItem[]>(
    () => estimatesQuery.data?.items ?? [],
    [estimatesQuery.data],
  );
  const contracts = React.useMemo<ContractListItem[]>(
    () => contractsQuery.data?.items ?? [],
    [contractsQuery.data],
  );

  // ── Detail sheet state ────────────────────────────────────────────────────
  const [openApprovalId, setOpenApprovalId] = React.useState<string | null>(null);

  // ── Derived sections ──────────────────────────────────────────────────────
  const now = Date.now();

  const needsSignoff = React.useMemo(
    () => deriveNeedsSignoff(approvals),
    [approvals],
  );
  const totalPending = React.useMemo(
    () => countPendingApprovals(approvals),
    [approvals],
  );
  const inFlight = React.useMemo(
    () => deriveInFlight(estimates, contracts),
    [estimates, contracts],
  );
  const recentlyShipped = React.useMemo(
    () => deriveRecentlyShipped(approvals, estimates, contracts, now),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [approvals, estimates, contracts],
  );
  const needsAttention = React.useMemo(
    () => deriveNeedsAttention(approvals, now),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [approvals],
  );

  // ── Loading / error ───────────────────────────────────────────────────────
  const isLoadingCore =
    approvalsQuery.isLoading &&
    estimatesQuery.isLoading &&
    contractsQuery.isLoading &&
    approvals.length === 0 &&
    estimates.length === 0 &&
    contracts.length === 0;

  const hasError =
    approvalsQuery.error || estimatesQuery.error || contractsQuery.error;

  const allEmpty =
    !isLoadingCore &&
    needsSignoff.length === 0 &&
    inFlight.length === 0 &&
    recentlyShipped.length === 0 &&
    needsAttention.length === 0;

  // ── Pull-to-refresh ───────────────────────────────────────────────────────
  const refresh = React.useCallback(() => {
    void qc.invalidateQueries({ queryKey: ["approvals"] });
    void qc.invalidateQueries({ queryKey: ["estimates"] });
    void qc.invalidateQueries({ queryKey: ["contracts"] });
    void qc.invalidateQueries({ queryKey: ["intelligence-kpis"] });
    void qc.invalidateQueries({ queryKey: ["intelligence-exceptions"] });
  }, [qc]);

  const onTouchStart = React.useRef<{ y: number; scrolledTop: boolean } | null>(null);
  const handleTouchStart = (e: React.TouchEvent) => {
    const target = e.currentTarget as HTMLDivElement;
    onTouchStart.current = { y: e.touches[0].clientY, scrolledTop: target.scrollTop <= 0 };
  };
  const handleTouchEnd = (e: React.TouchEvent) => {
    const start = onTouchStart.current;
    if (!start) return;
    const dy = e.changedTouches[0].clientY - start.y;
    if (start.scrolledTop && dy > 80) void refresh();
    onTouchStart.current = null;
  };

  // ── Derived KPI display values ────────────────────────────────────────────
  const mwLiveColor = kpis && kpis.mw_live > 0 ? "text-green-600" : "text-label-primary";
  const incidentsColor =
    kpis && kpis.active_incidents_p1_p2 > 0 ? "text-danger" : "text-green-600";
  const equipColor =
    kpis && kpis.at_risk_equipment_count > 0 ? "text-orange-500" : "text-label-primary";

  const today = formatToday();
  const lastRefreshed = formatLastRefreshed(approvalsQuery.dataUpdatedAt);
  const greeting = displayName ? `Good morning, ${displayName.split(" ")[0]}` : "Good morning";

  return (
    <MobileShell>
      <TopBar hero title={greeting} subtitle={today} />

      <div
        className="bg-bg-elevated min-h-full overflow-y-auto"
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      >
        {/* "As of" timestamp strip */}
        <div className="flex items-center justify-between px-4 pt-3 pb-1 text-footnote text-label-tertiary">
          <span>Last refreshed {lastRefreshed} · Pull to refresh</span>
          <button
            type="button"
            onClick={refresh}
            aria-label="Refresh"
            className="flex h-9 w-9 items-center justify-center text-accent active:opacity-60 no-tap-highlight"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>

        <div className="flex flex-col gap-4 px-4 pt-2 pb-8">
          {/* Error banner */}
          {hasError && (
            <ErrorBanner
              message="Couldn't load everything. Pull down to retry."
              onRetry={refresh}
              className="mx-0"
            />
          )}

          {/* ── KPI Strip ── */}
          {kpis && (
            <div>
              <p className="text-footnote font-semibold text-label-secondary mb-2 uppercase tracking-wide">
                Portfolio
              </p>
              <div className="flex gap-3 overflow-x-auto pb-1 snap-x snap-mandatory -mx-0 scroll-px-0 no-scrollbar">
                <KpiCard
                  label="MW Live"
                  value={kpis.mw_live.toFixed(1)}
                  unit="MW"
                  colorClass={mwLiveColor}
                />
                <KpiCard
                  label="Total ARR"
                  value={formatUsdCompact(kpis.total_arr_usd)}
                  unit="USD"
                />
                <KpiCard
                  label="Active Incidents"
                  value={String(kpis.active_incidents_p1_p2)}
                  unit="P1/P2"
                  colorClass={incidentsColor}
                />
                <KpiCard
                  label="Open Deals"
                  value={String(kpis.sites_in_pipeline)}
                  unit={formatUsdCompact(kpis.pipeline_value_usd) + " pipeline"}
                />
                <KpiCard
                  label="Customers"
                  value={String(kpis.active_customers)}
                  unit="active"
                />
                <KpiCard
                  label="At-Risk Equip."
                  value={String(kpis.at_risk_equipment_count)}
                  unit="items"
                  colorClass={equipColor}
                />
              </div>
            </div>
          )}

          {/* ── Exception Feed ── */}
          <div>
            <p className="text-footnote font-semibold text-label-secondary mb-2 uppercase tracking-wide">
              Requires Attention
            </p>
            <div className="rounded-2xl bg-bg-primary overflow-hidden">
              {exceptionsQuery.isLoading ? (
                <div className="px-4 py-6 text-footnote text-label-tertiary text-center">
                  Loading exceptions…
                </div>
              ) : exceptions.length === 0 ? (
                <div className="flex flex-col items-center gap-2 px-4 py-6">
                  <CheckCircle2 className="h-8 w-8 text-green-500" />
                  <p className="text-footnote text-label-secondary text-center">
                    All clear. No exceptions across any module.
                  </p>
                </div>
              ) : (
                <div className="px-4 pt-2 pb-1">
                  {exceptions.map((item) => (
                    <ExceptionRow key={item.id} item={item} />
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* ── Loading skeletons (core queue data) ── */}
          {isLoadingCore && (
            <>
              <SkelSectionCard />
              <SkelSectionCard />
            </>
          )}

          {/* ── Full-page empty state (only if queue sections also empty) ── */}
          {!isLoadingCore && allEmpty && exceptions.length === 0 && (
            <EmptyState
              icon={<Sparkles />}
              title="Nothing needs you right now."
              subtitle="Your morning is clear. Quill will surface things here as they come in."
            />
          )}

          {/* ── Section 1: Needs your sign-off ── */}
          {needsSignoff.length > 0 && (
            <SectionCard
              icon={<Zap className="h-4 w-4" />}
              title="Needs your sign-off"
              count={totalPending}
              viewAllHref={totalPending > 5 ? "/queue" : undefined}
              viewAllLabel={`View all ${totalPending} →`}
            >
              {needsSignoff.map((item) => (
                <NeedsSignoffRow
                  key={item.approval_id}
                  item={item}
                  onOpen={setOpenApprovalId}
                  now={now}
                />
              ))}
            </SectionCard>
          )}

          {/* ── Section 2: In-flight work ── */}
          {inFlight.length > 0 && (
            <SectionCard
              icon={<RefreshCw className="h-4 w-4" />}
              title="In-flight work"
              count={inFlight.length}
            >
              {inFlight.map((item) => (
                <InFlightRow key={item.id} item={item} now={now} />
              ))}
            </SectionCard>
          )}

          {/* ── Section 3: Recently shipped ── */}
          {recentlyShipped.length > 0 && (
            <SectionCard
              icon={<CheckCircle2 className="h-4 w-4" />}
              title="Recently shipped"
              count={recentlyShipped.length}
              viewAllHref="/audit"
              viewAllLabel="View activity →"
            >
              {recentlyShipped.map((item) => (
                <RecentItemRow key={item.id} item={item} now={now} />
              ))}
            </SectionCard>
          )}

          {/* ── Section 4: Needs attention (stale) ── */}
          {needsAttention.length > 0 && (
            <SectionCard
              icon={<AlertTriangle className="h-4 w-4" />}
              title="Needs attention"
              count={needsAttention.length}
            >
              {needsAttention.map((item) => (
                <NeedsAttentionRow
                  key={item.approval_id}
                  item={item}
                  onOpen={setOpenApprovalId}
                  now={now}
                />
              ))}
            </SectionCard>
          )}

          {/* ── Quiet hours hint ── */}
          {needsSignoff.length > 0 && (
            <p className="text-center text-footnote text-label-quaternary px-4">
              <Clock className="inline h-3 w-3 mr-1 align-middle" />
              Items sorted by urgency. Tap any row to review.
            </p>
          )}

          {/* ── Quick Links ── */}
          <div>
            <p className="text-footnote font-semibold text-label-secondary mb-2 uppercase tracking-wide">
              Go to
            </p>
            <div className="grid grid-cols-3 gap-2">
              {QUICK_LINKS.map(({ href, label, icon: Icon }) => (
                <Link
                  key={href}
                  href={href}
                  className="flex flex-col items-center gap-1.5 rounded-xl bg-bg-primary px-2 py-4 text-center active:opacity-70 no-tap-highlight"
                >
                  <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-bg-elevated text-label-secondary">
                    <Icon className="h-5 w-5" strokeWidth={1.75} />
                  </span>
                  <span className="text-caption-1 font-medium text-label-primary">{label}</span>
                </Link>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Approval detail sheet */}
      <ApprovalDetailSheet
        approvalId={openApprovalId}
        onClose={() => setOpenApprovalId(null)}
      />
    </MobileShell>
  );
}

/* ── Helpers ─────────────────────────────────────────────────────────────── */

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

function formatRelTime(isoStr: string): string {
  try {
    const delta = (Date.now() - new Date(isoStr).getTime()) / 1000;
    if (delta < 60) return "just now";
    if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
    if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
    return `${Math.floor(delta / 86400)}d ago`;
  } catch {
    return "";
  }
}

function formatUsdCompact(v: number): string {
  if (v >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(1)}B`;
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
  return `$${v.toFixed(0)}`;
}
