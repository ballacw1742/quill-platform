"use client";

import * as React from "react";
import { Inbox, Search, SlidersHorizontal, X } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { HelpHint } from "@/components/ui/help-hint";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { ApprovalRow } from "@/components/queue/ApprovalRow";
import { FilterSheet, DEFAULT_FILTERS, type QueueFilterValue } from "@/components/queue/FilterSheet";
import { ApprovalDetailSheet } from "@/components/queue/ApprovalDetailSheet";
import { useApprovals } from "@/lib/api";
import type { ApprovalItem, Lane } from "@/lib/schemas";
import { sortItemsForLane, LANE_META } from "@/components/queue/laneMeta";
import { laneTabLabel } from "@/lib/agent-meta";
import { OnboardingOverlay } from "@/components/onboarding/OnboardingOverlay";

/**
 * /queue — iOS-redesign main screen, per MOBILE_UX_SPEC §"Tab 1 — Queue".
 *
 * Layout (top → bottom):
 *   1. TopBar:  "Queue" title + pending counter + search-toggle + filter button.
 *   2. (optional) expanded search bar.
 *   3. SegmentedControl: lane switch (Mandatory / Spot-check / Auto), with
 *      live counts in the segment chips. Default "Spot-check".
 *   4. Pull-to-refresh container (native iOS overscroll behaviour).
 *   5. List of ApprovalRow (rows use ListRow + SwipeRow primitives).
 *   6. Empty state per lane.
 *
 * Detail view: tapping a row opens ApprovalDetailSheet (BottomSheet) over
 * the queue. No navigation — the queue stays mounted and refreshes after
 * the decision.
 */

// Tab order matches the way Charles thinks about the queue:
//   Yours → Two-signer → Auto.
// Per COPY_GUIDE the lane segmented control uses these single-word labels.
const LANE_TABS: { value: Lane; label: string }[] = [
  { value: "tier-1-spotcheck", label: laneTabLabel("tier-1-spotcheck") }, // "Yours"
  { value: "tier-0-mandatory", label: laneTabLabel("tier-0-mandatory") }, // "Two-signer"
  { value: "tier-2-auto", label: laneTabLabel("tier-2-auto") }, // "Auto"
];

const DEFAULT_LANE: Lane = "tier-1-spotcheck";

export default function QueuePage() {
  const { data, isLoading } = useApprovals();
  const qc = useQueryClient();
  const items = React.useMemo<ApprovalItem[]>(() => data ?? [], [data]);

  const [lane, setLane] = React.useState<Lane>(DEFAULT_LANE);
  const [filters, setFilters] = React.useState<QueueFilterValue>(DEFAULT_FILTERS);
  const [search, setSearch] = React.useState("");
  const [searchOpen, setSearchOpen] = React.useState(false);
  const [filterOpen, setFilterOpen] = React.useState(false);
  const [openId, setOpenId] = React.useState<string | null>(null);

  const agents = React.useMemo(
    () => Array.from(new Set(items.map((i) => i.agent_id))).sort(),
    [items],
  );
  const workflows = React.useMemo(
    () => Array.from(new Set(items.map((i) => i.workflow))).sort(),
    [items],
  );

  const filteredAll = React.useMemo<ApprovalItem[]>(() => {
    const q = search.trim().toLowerCase();
    return items.filter((i) => {
      if (filters.agent !== "all" && i.agent_id !== filters.agent) return false;
      if (filters.workflow !== "all" && i.workflow !== filters.workflow) return false;
      if (filters.age !== "any") {
        const age = Date.now() - +new Date(i.created_at);
        const map: Record<"1h" | "24h" | "stale", { ms: number; invert?: boolean }> = {
          "1h": { ms: 3_600_000 },
          "24h": { ms: 86_400_000 },
          stale: { ms: 86_400_000, invert: true },
        };
        const m = map[filters.age];
        if (m.invert ? age <= m.ms : age > m.ms) return false;
      }
      if (q) {
        const blob =
          `${i.agent_id} ${i.workflow} ${i.summary ?? ""} ${i.rationale ?? ""} ${i.approval_id}`.toLowerCase();
        if (!blob.includes(q)) return false;
      }
      return true;
    });
  }, [items, filters, search]);

  const lanes = React.useMemo(
    () => ({
      "tier-0-mandatory": sortItemsForLane(filteredAll, "tier-0-mandatory"),
      "tier-1-spotcheck": sortItemsForLane(filteredAll, "tier-1-spotcheck"),
      "tier-2-auto": sortItemsForLane(filteredAll, "tier-2-auto"),
    }),
    [filteredAll],
  );

  const totalPending = items.filter((i) => i.status === "pending").length;
  const activeRows = lanes[lane];

  // Pull-to-refresh: rely on browser overscroll + an explicit refresh handler.
  const refresh = React.useCallback(
    () => qc.invalidateQueries({ queryKey: ["approvals"] }),
    [qc],
  );
  // Pull-to-refresh handled at the browser level on iOS Safari for a real PWA
  // installed instance. For browser-tab usage, we provide a manual refresh by
  // triggering invalidate on viewport-top overscroll start.
  const onTouchStart = React.useRef<{ y: number; scrolledTop: boolean } | null>(null);
  const handleTouchStart = (e: React.TouchEvent) => {
    const target = e.currentTarget as HTMLDivElement;
    onTouchStart.current = { y: e.touches[0].clientY, scrolledTop: target.scrollTop <= 0 };
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

  return (
    <MobileShell>
      <OnboardingOverlay />
      <TopBar
        title="Queue"
        right={
          <div className="flex items-center gap-1">
            <button
              type="button"
              aria-label={searchOpen ? "Close search" : "Search"}
              onClick={() => {
                setSearchOpen((v) => {
                  if (v) setSearch("");
                  return !v;
                });
              }}
              className="flex h-11 w-11 items-center justify-center text-accent active:opacity-60 no-tap-highlight"
            >
              {searchOpen ? <X className="h-5 w-5" /> : <Search className="h-5 w-5" />}
            </button>
            <button
              type="button"
              aria-label="Filter"
              onClick={() => setFilterOpen(true)}
              className="flex h-11 w-11 items-center justify-center text-accent active:opacity-60 no-tap-highlight"
            >
              <SlidersHorizontal className="h-5 w-5" />
            </button>
          </div>
        }
      />

      <div
        className="flex flex-col"
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      >
        {searchOpen && (
          <div className="px-4 pt-2 pb-2 bg-bg">
            <Input
              autoFocus
              placeholder="Search…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-11 rounded-md bg-bg-elevated border-transparent text-body"
            />
          </div>
        )}

        <div className="px-4 pt-2 pb-3 bg-bg">
          <div className="flex items-baseline justify-between mb-2">
            <span className="text-footnote text-label-secondary inline-flex items-center gap-1">
              {totalPending} pending
              <HelpHint term="lane" ariaLabel="What do these tabs mean?" />
            </span>
            <span className="text-footnote text-label-tertiary">
              {activeRows.length} in lane
            </span>
          </div>
          <SegmentedControl
            value={lane}
            onChange={setLane}
            options={LANE_TABS.map((t) => ({
              value: t.value,
              label: t.label,
              badge: lanes[t.value].length,
            }))}
            ariaLabel="Switch lane"
          />
        </div>

        <div className="flex-1 bg-bg-elevated">
          {isLoading ? (
            <SkeletonRows />
          ) : activeRows.length === 0 ? (
            <EmptyLaneState lane={lane} />
          ) : (
            <ul className="divide-y divide-separator/40 bg-bg-tertiary">
              {activeRows.map((item) => (
                <li key={item.approval_id}>
                  <ApprovalRow
                    item={item}
                    onOpen={(id) => setOpenId(id)}
                    onApprove={(id) => {
                      // Swipe-approve still requires biometric; route through the
                      // detail sheet's approve flow rather than minting an
                      // unauthenticated mutation here. We open the sheet pre-
                      // armed for approve; the sheet auto-fires the biometric.
                      setOpenId(id);
                    }}
                    onReject={(id) => setOpenId(id)}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <FilterSheet
        open={filterOpen}
        onOpenChange={setFilterOpen}
        value={filters}
        onChange={setFilters}
        agents={agents}
        workflows={workflows}
      />

      <ApprovalDetailSheet
        approvalId={openId}
        onClose={() => setOpenId(null)}
      />
    </MobileShell>
  );
}

function SkeletonRows() {
  return (
    <ul className="divide-y divide-separator/40 bg-bg-tertiary">
      {Array.from({ length: 6 }).map((_, i) => (
        <li
          key={i}
          className="flex items-center gap-3 px-4 py-3 min-h-[56px] animate-shimmer"
        >
          <span className="h-7 w-7 shrink-0 rounded-md bg-bg-elevated" />
          <div className="flex-1 space-y-1.5">
            <span className="block h-3.5 w-2/3 rounded-sm bg-bg-elevated" />
            <span className="block h-3 w-5/6 rounded-sm bg-bg-elevated" />
          </div>
        </li>
      ))}
    </ul>
  );
}

function EmptyLaneState({ lane }: { lane: Lane }) {
  // Per COPY_GUIDE §"Empty states / Queue tab".
  const copy: Record<Lane, { title: string; subtitle: string }> = {
    "tier-0-mandatory": {
      title: "No two-signer items.",
      subtitle:
        "These are big-impact items that need both you and a partner.",
    },
    "tier-1-spotcheck": {
      title: "Nothing to sign off.",
      subtitle:
        "When the helpers find something needing your eyes, it'll show up here.",
    },
    "tier-2-auto": {
      title: "Nothing handled automatically yet.",
      subtitle:
        "Auto-handled items will show up here so you can spot-check anytime.",
    },
  };
  const c = copy[lane];
  return <EmptyState icon={<Inbox />} title={c.title} subtitle={c.subtitle} />;
}
