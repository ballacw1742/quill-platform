"use client";

import * as React from "react";
import { Inbox, Search, SlidersHorizontal, X } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { MobileShell } from "@/components/layout/MobileShell";
import { HelpHint } from "@/components/ui/help-hint";
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
import { cn } from "@/lib/utils";

/**
 * /queue — Lovable-reskinned approval queue, per MOBILE_UX_SPEC §"Tab 1 — Queue".
 *
 * Layout (top → bottom):
 *   1. TopBar:  "Queue" title + search-toggle + filter button (sticky).
 *   2. (optional) expanded search bar.
 *   3. Custom lane tab grid: 3 cols, bg-bg-elevated, active tab bg-bg shadow-card,
 *      with pending-count badges. Lane description below.
 *   4. Pull-to-refresh container.
 *   5. QueueCategoryGroup list.
 *   6. Empty state per lane.
 *
 * Decision flow, websocket, and all prod data hooks PRESERVED:
 *   - useApprovals() from @/lib/api — bare ApprovalItem[]
 *   - useDecide() called inside ApprovalDetailSheet via prod's decision path
 *   - useApprovalsSocket() subscribed inside MobileShell (unchanged)
 *   - Lane semantics: tier-0-mandatory / tier-1-spotcheck / tier-2-auto (prod API integer → string mapping in api.ts)
 */

// Tab order matches the way Charles thinks about the queue: Yours → Two-signer → Auto.
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
  React.useEffect(() => {
    const stored = loadExpandedCategories();
    const initial = computeInitialExpansion(activeCategories, stored);
    setExpandedCategories((prev) => {
      if (!expansionInitialized.current) {
        expansionInitialized.current = true;
        return initial;
      }
      const merged = new Set(prev);
      for (const cat of activeCategories) {
        if (cat.hasPending) merged.add(cat.label);
      }
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
        saveExpandedCategories(Array.from(next));
        return next;
      });
    },
    [],
  );

  // Pull-to-refresh: rely on browser overscroll + explicit refresh handler.
  const refresh = React.useCallback(
    () => qc.invalidateQueries({ queryKey: ["approvals"] }),
    [qc],
  );
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

  const activeLaneMeta = LANE_META[lane];

  return (
    <MobileShell>
      <OnboardingOverlay />

      {/* Sticky toolbar: search + filter buttons */}
      <div className="sticky top-0 z-20 flex items-center justify-end gap-1 border-b border-hairline bg-chrome px-3 py-1">
        <button
          type="button"
          aria-label={searchOpen ? "Close search" : "Search"}
          onClick={() => {
            setSearchOpen((v) => {
              if (v) setSearch("");
              return !v;
            });
          }}
          className="no-tap-highlight flex h-10 w-10 items-center justify-center text-accent active:opacity-60"
        >
          {searchOpen ? <X className="h-5 w-5" /> : <Search className="h-5 w-5" />}
        </button>
        <button
          type="button"
          aria-label="Filter"
          onClick={() => setFilterOpen(true)}
          className="no-tap-highlight flex h-10 w-10 items-center justify-center text-accent active:opacity-60"
        >
          <SlidersHorizontal className="h-5 w-5" />
        </button>
      </div>

      <div
        className="flex flex-col"
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      >
        {searchOpen && (
          <div className="bg-bg px-4 pt-2 pb-2">
            <Input
              autoFocus
              placeholder="Search approvals…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="text-body h-11 rounded-md border-transparent bg-bg-elevated"
            />
          </div>
        )}

        {/* Lane selector + pending summary */}
        <div className="bg-bg px-4 pt-2 pb-3">
          <div className="mb-2 flex items-baseline justify-between">
            <span className="text-footnote text-label-secondary inline-flex items-center gap-1">
              {totalPending} pending
              <HelpHint term="lane" ariaLabel="What do these tabs mean?" />
            </span>
            <span className="text-footnote text-label-tertiary">
              {activeRows.length} in lane
            </span>
          </div>

          {/* Lovable-style tab grid: 3 cols, bg-bg-elevated container, active = bg-bg shadow-card */}
          <div
            role="tablist"
            aria-label="Switch lane"
            className="grid grid-cols-3 gap-1 rounded-lg bg-bg-elevated p-1"
          >
            {LANE_TABS.map((t) => {
              const count = lanes[t.value].length;
              const active = lane === t.value;
              return (
                <button
                  key={t.value}
                  role="tab"
                  aria-selected={active}
                  onClick={() => setLane(t.value)}
                  className={cn(
                    "text-footnote flex h-8 items-center justify-center gap-1.5 rounded-md font-medium transition-colors duration-state no-tap-highlight",
                    active
                      ? "bg-bg text-label-primary shadow-card"
                      : "text-label-secondary active:opacity-70",
                  )}
                >
                  {t.label}
                  {count > 0 && (
                    <span
                      className={cn(
                        "text-caption-2 flex h-4 min-w-[16px] items-center justify-center rounded-full px-1 font-semibold",
                        active
                          ? "bg-accent text-accent-foreground"
                          : "bg-separator/40 text-label-secondary",
                      )}
                    >
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* Lane description — per Lovable design */}
          {activeLaneMeta?.description && (
            <p className="text-footnote mt-2 text-label-tertiary">
              {activeLaneMeta.description}
            </p>
          )}
        </div>

        <div className="flex-1 bg-bg-elevated">
          {error ? (
            <div className="mx-4 mt-4 rounded-xl bg-danger/10 px-4 py-3">
              <p className="text-footnote text-danger">
                Couldn't load your queue. Try again.
              </p>
              <button
                onClick={() => refetch()}
                className="text-footnote mt-1 font-semibold text-danger underline"
              >
                Retry
              </button>
            </div>
          ) : isLoading ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 5 }).map((_, i) => (
                <div
                  key={i}
                  className="h-16 animate-shimmer rounded-xl bg-bg-tertiary"
                />
              ))}
            </div>
          ) : activeRows.length === 0 ? (
            <EmptyLaneState lane={lane} />
          ) : (
            <div className="divide-y divide-hairline">
              {activeCategories.map((category) => (
                <QueueCategoryGroup
                  key={category.label}
                  category={category}
                  open={expandedCategories.has(category.label)}
                  onToggle={() => toggleCategory(category.label)}
                  onOpen={(id) => setOpenId(id)}
                  onApprove={(id) => {
                    // Swipe-approve routes through the detail sheet's approve
                    // flow rather than minting an unauthenticated mutation here.
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
  const copy: Record<Lane, { title: string; subtitle: string }> = {
    "tier-0-mandatory": {
      title: "No two-signer items.",
      subtitle: "These are big-impact items that need both you and a partner.",
    },
    "tier-1-spotcheck": {
      title: "Nothing to sign off.",
      subtitle: "When the helpers find something needing your eyes, it'll show up here.",
    },
    "tier-2-auto": {
      title: "Nothing handled automatically yet.",
      subtitle: "Auto-handled items will show up here so you can spot-check any time.",
    },
  };
  const c = copy[lane];
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-8 py-16 text-center">
      <Inbox className="h-10 w-10 text-label-quaternary" aria-hidden="true" />
      <p className="text-headline text-label-primary">{c.title}</p>
      <p className="text-footnote max-w-xs text-label-secondary">{c.subtitle}</p>
    </div>
  );
}
