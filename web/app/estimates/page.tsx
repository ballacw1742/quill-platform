"use client";

import * as React from "react";
import Link from "next/link";
import {
  Calculator,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Loader2,
  Plus,
  Ruler,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { ListRow } from "@/components/ui/list-row";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { UploadEstimateSheet } from "@/components/estimates/UploadEstimateSheet";
import { useListEstimates, type EstimateListItem } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * /estimates — Phase G.5 dedicated tab for the drawing-driven cost +
 * schedule flow.
 *
 * Layout (per MOBILE_UX_SPEC §"List rows" + DESIGN_SYSTEM §7):
 *
 *   1. TopBar: "Estimates" title + right-side "+ New" pill.
 *   2. Optional segmented control (All / In flight / Done).
 *   3. List of EstimateRow items (or empty state).
 *   4. Pull-to-refresh.
 *
 * Tap a row → /estimates/[upload_id] when the estimate is still in flight,
 * or /documents/[id] when a published cost_schedule_package exists.
 *
 * Voice (COPY_GUIDE):
 *   - "No estimates yet." — sentence case, plain.
 *   - "+ New" instead of "Create estimate" / "Upload drawings".
 *   - "Class N estimate" not "AACE Class N estimate" in row chips.
 *
 * Note on the data source: the /v1/estimates routes don't expose a list
 * endpoint, so this page reuses /v1/documents under the hood and merges
 * the two relevant artifact types (aace_classification +
 * cost_schedule_package) by metadata.upload_id. See useListEstimates in
 * lib/api.ts. The Documents tab continues to show every artifact type;
 * this tab is the focused entry point for the upload flow.
 */

type Filter = "all" | "in_flight" | "done";

const FILTER_OPTIONS: ReadonlyArray<{ value: Filter; label: string }> = [
  { value: "all", label: "All" },
  { value: "in_flight", label: "In flight" },
  { value: "done", label: "Done" },
];

export default function EstimatesPage() {
  const qc = useQueryClient();
  const { data, isLoading, error, refetch, dataUpdatedAt } = useListEstimates();

  const [filter, setFilter] = React.useState<Filter>("all");
  const [uploadOpen, setUploadOpen] = React.useState(false);

  const allItems = data?.items ?? [];

  const visibleItems = React.useMemo(() => {
    if (filter === "all") return allItems;
    if (filter === "done")
      return allItems.filter((it) => it.status_hint === "published");
    if (filter === "in_flight")
      return allItems.filter((it) => it.status_hint !== "published");
    return allItems;
  }, [allItems, filter]);

  // Pull-to-refresh — same gesture pattern as /documents and /queue.
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
      void qc.invalidateQueries({ queryKey: ["documents"] });
      void refetch();
    }
    onTouchStart.current = null;
  };

  return (
    <MobileShell>
      <TopBar
        title="Estimates"
        right={
          <button
            type="button"
            onClick={() => setUploadOpen(true)}
            aria-label="New estimate"
            className="-mr-2 inline-flex h-9 items-center gap-1 rounded-full bg-accent/10 px-3 text-callout font-medium text-accent active:opacity-70 no-tap-highlight"
          >
            <Plus className="h-4 w-4" strokeWidth={2.25} />
            <span>New</span>
          </button>
        }
      />

      <div
        className="flex flex-col"
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      >
        {/* Segmented filter */}
        <div className="px-4 pt-2 pb-3 bg-bg">
          <SegmentedControl
            value={filter}
            onChange={setFilter}
            options={FILTER_OPTIONS}
            ariaLabel="Filter estimates by status"
          />
        </div>

        <div className="flex-1 bg-bg-elevated min-h-[60vh]">
          {error && (
            <ErrorBanner
              message="Couldn't load your estimates. Try again."
              onRetry={() => void refetch()}
            />
          )}
          {isLoading && allItems.length === 0 ? (
            <SkeletonRows />
          ) : visibleItems.length === 0 ? (
            <EstimatesEmptyState
              filter={filter}
              onNewEstimate={() => setUploadOpen(true)}
            />
          ) : (
            <ul
              className="divide-y divide-separator/40 bg-bg-tertiary"
              aria-label="Estimates"
            >
              {visibleItems.map((item, i) => (
                <li key={item.upload_id}>
                  <EstimateRow
                    item={item}
                    hideDivider={i === visibleItems.length - 1}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Footer status */}
        {allItems.length > 0 && (
          <div className="bg-bg-elevated px-4 pb-6 pt-2 text-footnote text-label-tertiary">
            Last refreshed {formatLastRefreshed(dataUpdatedAt)}
          </div>
        )}
      </div>

      <UploadEstimateSheet open={uploadOpen} onOpenChange={setUploadOpen} />
    </MobileShell>
  );
}

/* ── Estimate row ───────────────────────────────────────────────────────── */

function EstimateRow({
  item,
  hideDivider,
}: {
  item: EstimateListItem;
  hideDivider?: boolean;
}) {
  const isPublished = item.status_hint === "published";
  const Icon = isPublished ? Calculator : Ruler;
  const tone: "accent" | "info" = isPublished ? "accent" : "info";

  // Tap target — published packages route to the Documents detail page so the
  // user gets the full cost rows / Gantt / risk view; in-flight estimates go
  // to the progress page.
  const href =
    isPublished && item.package_document_id
      ? `/documents/${encodeURIComponent(item.package_document_id)}`
      : `/estimates/${encodeURIComponent(item.upload_id)}`;

  const dateAgo = formatRelative(item.created_at);

  const subtitle = (
    <span className="truncate">
      <span className="text-label-primary">
        {item.aace_class ? `Class ${item.aace_class} estimate` : "Estimate"}
      </span>
      <span className="text-label-tertiary"> · </span>
      <StatusInline isPublished={isPublished} />
      {dateAgo && (
        <>
          <span className="text-label-tertiary"> · </span>
          {dateAgo}
        </>
      )}
    </span>
  );

  const chip = (
    <span className="inline-flex items-center text-callout font-medium tabular-nums text-label-primary">
      {isPublished && typeof item.total_usd === "number"
        ? formatUsd(item.total_usd)
        : (
          <span className="text-footnote text-label-tertiary">
            {isPublished ? "—" : "In flight"}
          </span>
        )}
    </span>
  );

  return (
    <ListRow
      icon={<Icon className="h-4 w-4" strokeWidth={1.75} />}
      iconTone={tone}
      title={item.project_label}
      subtitle={subtitle}
      chip={chip}
      href={href}
      hideDivider={hideDivider}
      ariaLabel={`Estimate: ${item.project_label}`}
    />
  );
}

function StatusInline({ isPublished }: { isPublished: boolean }) {
  if (isPublished) {
    return (
      <span className="inline-flex items-center gap-1 text-label-secondary">
        <CheckCircle2 className="h-3 w-3 text-success" strokeWidth={2} />
        Published
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-label-secondary">
      <CircleDot className="h-3 w-3 text-info" strokeWidth={2} />
      In flight
    </span>
  );
}

/* ── Empty state ────────────────────────────────────────────────────────── */

function EstimatesEmptyState({
  filter,
  onNewEstimate,
}: {
  filter: Filter;
  onNewEstimate: () => void;
}) {
  if (filter === "in_flight") {
    return (
      <EmptyState
        icon={<Loader2 />}
        title="Nothing in flight."
        subtitle="When you start an estimate from drawings, it'll show up here while it runs."
      />
    );
  }
  if (filter === "done") {
    return (
      <EmptyState
        icon={<CheckCircle2 />}
        title="No published estimates yet."
        subtitle="Approved cost & schedule packages will collect here once they ship."
      />
    );
  }
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <span
        className={cn(
          "flex h-14 w-14 items-center justify-center rounded-2xl",
          "bg-accent/10 text-accent mb-4",
        )}
        aria-hidden="true"
      >
        <Calculator className="h-7 w-7" strokeWidth={1.5} />
      </span>
      <div className="text-title-3 text-label-primary">
        No estimates yet.
      </div>
      <div className="mt-1 max-w-[28ch] text-body text-label-secondary">
        Tap + New to upload drawings and generate your first cost + schedule
        estimate.
      </div>
      <button
        type="button"
        onClick={onNewEstimate}
        className="mt-5 inline-flex h-11 items-center gap-1.5 rounded-md bg-accent px-4 text-headline text-white active:opacity-85 no-tap-highlight"
      >
        <Plus className="h-4 w-4" strokeWidth={2.25} />
        New estimate
        <ChevronRight className="h-4 w-4 opacity-80" />
      </button>
    </div>
  );
}

function SkeletonRows() {
  return (
    <ul
      className="divide-y divide-separator/40 bg-bg-tertiary"
      aria-label="Loading estimates"
    >
      {Array.from({ length: 5 }).map((_, i) => (
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

/* ── Helpers ────────────────────────────────────────────────────────────── */

function formatUsd(n: number): string {
  if (!Number.isFinite(n)) return "—";
  // Compact for big numbers; the row is narrow.
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 10_000) return `$${(n / 1000).toFixed(0)}K`;
  if (Math.abs(n) >= 1000) return `$${(n / 1000).toFixed(1)}K`;
  return `$${Math.round(n).toLocaleString()}`;
}

function formatRelative(iso: string): string {
  const ts = +new Date(iso);
  if (!Number.isFinite(ts)) return "";
  const seconds = Math.max(1, Math.floor((Date.now() - ts) / 1000));
  if (seconds < 60) return "just now";
  const mins = Math.floor(seconds / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  return `${months}mo ago`;
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
