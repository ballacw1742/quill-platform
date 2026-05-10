"use client";

import * as React from "react";
import { Inbox, Search, SlidersHorizontal, X } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { HelpHint } from "@/components/ui/help-hint";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { FilterSheet, DEFAULT_FILTERS, type QueueFilterValue } from "@/components/queue/FilterSheet";
import { ApprovalDetailSheet } from "@/components/queue/ApprovalDetailSheet";
import { QueueCategoryGroup } from "@/components/queue/QueueCategoryGroup";
import { useApprovals } from "@/lib/api";
import type { ApprovalItem, Lane } from "@/lib/schemas";
import { sortItemsForLane, LANE_META } from "@/components/queue/laneMeta";
import { laneTabLabel } from "@/lib/agent-meta";
import {
  groupItemsByCategory,
  loadExpandedCategories,
  saveExpandedCategories,
  computeInitialExpansion,
  type QueueCategory,
} from "@/lib/queue-categories";
import { OnboardingOverlay } from "@/components/onboarding/OnboardingOverlay";
import { ErrorBanner } from "@/components/ui/error-banner";
import { SkelList } from "@/components/ui/skeletons";

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
  const { data, isLoading, error, refetch } = useApprovals();
  const qc = useQueryClient();
  const items = React.useMemo<ApprovalItem[]>(() => data ?? [], [data]);

  const [lane, setLane] = React.useState<Lane>(DEFAULT_LANE);
  const [filters, setFilters] = React.useState<QueueFilterValue>(DEFAULT_FILTERS);
  const [search, setSearch] = React.useState("");
  const [searchOpen, setSearchOpen] = React.useState(false);
  const [filterOpen, setFilterOpen] = React.useState(false);
  const [openId, setOpenId] = React.useState<string | null>(null);

  // Category expansion state — keyed by display label.
  // Initialised on first render from localStorage + default-expansion logic.
  const [expandedCategories, setExpandedCategories] = React.useState<Set<string>>(
    () => new Set<string>(),
  );
  const expansionInitialized = React.useRef(false);

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

  // Group active rows into categories.
  const activeCategories = React.useMemo<QueueCategory[]>(
    () => groupItemsByCategory(activeRows),
    [activeRows],
  );

  // Initialise expansion state from localStorage once we have categories.
  // Re-run whenever the lane or categories change so newly-pending items
  // force-expand even mid-session.
  React.useEffect(() => {
    const stored = loadExpandedCategories();
    const initial = computeInitialExpansion(activeCategories, stored);
    setExpandedCategories((prev) => {
      // On first load: use computed initial.
      // On subsequent changes (lane switch, filter): merge — keep any
      // manually-expanded cats the user set this session, but force-expand
      // anything with pending items.
      if (!expansionInitialized.current) {
        expansionInitialized.current = true;
        return initial;
      }
      const merged = new Set(prev);
      for (const cat of activeCategories) {
        if (cat.hasPending) merged.add(cat.label);
      }
      // Drop labels for categories that no longer exist in this lane view.
      const validLabels = new Set(activeCategories.map((c) => c.label));
      for (const label of merged) {
        if (!validLabels.has(label)) merged.delete(label);
      }
      return merged;
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lane, activeCategories.length]);

  const toggleCategory = React.useCallback(
    (label: string) => {
      setExpandedCategories((prev) => {
        const next = new Set(prev);
        if (next.has(label)) {
          next.delete(label);
        } else {
          next.add(label);
        }
        // Persist updated expansion state.
        saveExpandedCategories(Array.from(next));
        return next;
      });
    },
    [],
  );

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
          {error && (
            <ErrorBanner
              message="Couldn't load your queue. Try again."
              onRetry={() => refetch()}
            />
          )}
          {isLoading ? (
            <SkelList ariaLabel="Loading queue" count={6} />
          ) : activeRows.length === 0 ? (
            <EmptyLaneState lane={lane} />
          ) : (
            <div className="divide-y divide-separator/20">
              {activeCategories.map((category) => (
                <QueueCategoryGroup
                  key={category.label}
                  category={category}
                  open={expandedCategories.has(category.label)}
                  onToggle={() => toggleCategory(category.label)}
                  onOpen={(id) => setOpenId(id)}
                  onApprove={(id) => {
                    // Swipe-approve still requires biometric; route through the
                    // detail sheet's approve flow rather than minting an
                    // unauthenticated mutation here.
                    setOpenId(id);
                  }}
                  onReject={(id) => setOpenId(id)}
                />
              ))}
            </div>
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
