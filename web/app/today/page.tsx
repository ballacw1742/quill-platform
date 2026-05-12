"use client";

import * as React from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  RefreshCw,
  Sparkles,
  Zap,
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
import { useApprovals, useListEstimates, useContractsList } from "@/lib/api";
import type { ApprovalItem } from "@/lib/schemas";
import type { ContractListItem } from "@/lib/schemas";
import type { EstimateListItem } from "@/lib/api";
import {
  deriveNeedsSignoff,
  deriveInFlight,
  deriveRecentlyShipped,
  deriveNeedsAttention,
  countPendingApprovals,
} from "@/lib/today";

/**
 * /today — Daily Brief: actual content inline, not just counts + links.
 *
 * Sections appear only when they have real data. If all four are empty,
 * the full-page empty state is shown instead.
 *
 * Pull-to-refresh implemented as touch-overscroll gesture (same pattern
 * as /queue and /estimates).
 */

export default function TodayPage() {
  const qc = useQueryClient();

  // ── Data fetching ─────────────────────────────────────────────────────────
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
  const [openApprovalId, setOpenApprovalId] = React.useState<string | null>(
    null,
  );

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

  // ── Loading / error state ─────────────────────────────────────────────────
  const isLoading =
    approvalsQuery.isLoading &&
    estimatesQuery.isLoading &&
    contractsQuery.isLoading &&
    approvals.length === 0 &&
    estimates.length === 0 &&
    contracts.length === 0;

  const hasError =
    approvalsQuery.error || estimatesQuery.error || contractsQuery.error;

  const allEmpty =
    !isLoading &&
    needsSignoff.length === 0 &&
    inFlight.length === 0 &&
    recentlyShipped.length === 0 &&
    needsAttention.length === 0;

  // ── Pull-to-refresh ───────────────────────────────────────────────────────
  const refresh = React.useCallback(() => {
    void qc.invalidateQueries({ queryKey: ["approvals"] });
    void qc.invalidateQueries({ queryKey: ["estimates"] });
    void qc.invalidateQueries({ queryKey: ["contracts"] });
  }, [qc]);

  const onTouchStart = React.useRef<{ y: number; scrolledTop: boolean } | null>(
    null,
  );
  const handleTouchStart = (e: React.TouchEvent) => {
    const target = e.currentTarget as HTMLDivElement;
    onTouchStart.current = {
      y: e.touches[0].clientY,
      scrolledTop: target.scrollTop <= 0,
    };
  };
  const handleTouchEnd = (e: React.TouchEvent) => {
    const start = onTouchStart.current;
    if (!start) return;
    const dy = e.changedTouches[0].clientY - start.y;
    if (start.scrolledTop && dy > 80) {
      void refresh();
    }
    onTouchStart.current = null;
  };

  // ── Timestamp ─────────────────────────────────────────────────────────────
  const today = formatToday();
  const lastRefreshed = formatLastRefreshed(
    approvalsQuery.dataUpdatedAt,
  );

  return (
    <MobileShell>
      <TopBar hero title="Today" subtitle={today} />

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

          {/* Loading skeletons */}
          {isLoading && (
            <>
              <SkelSectionCard />
              <SkelSectionCard />
              <SkelSectionCard />
            </>
          )}

          {/* Full-page empty state */}
          {!isLoading && allEmpty && (
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

          {/* ── Quiet hours hint (shown when sign-off section has items) ── */}
          {needsSignoff.length > 0 && (
            <p className="text-center text-footnote text-label-quaternary px-4">
              <Clock className="inline h-3 w-3 mr-1 align-middle" />
              Items sorted by urgency. Tap any row to review.
            </p>
          )}
        </div>
      </div>

      {/* Approval detail sheet — opens over the page, no navigation */}
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
