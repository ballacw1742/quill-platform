"use client";

import * as React from "react";
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
import { UploadEstimateSheet } from "@/components/estimates/UploadEstimateSheet";
import { useListEstimates, type EstimateListItem } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * /estimates — Phase G.5 dedicated tab for the drawing-driven cost +
 * schedule flow.
 *
 * Layout (Lovable redesign, LOVABLE_PORT_CONTRACT §estimates):
 *
 *   1. TopBar: "Estimates" title + right-side "+ New" pill.
 *   2. Segmented filter (All / In flight / Done) — pill-tab style.
 *   3. Card-wrapped list of EstimateRow items (or empty state).
 *   4. Pull-to-refresh.
 *
 * Tap a row → /estimates/[upload_id] for in-flight estimates,
 * or /documents/[id] when a published cost_schedule_package exists.
 *
 * Data: useListEstimates() → { items: EstimateListItem[]; total }
 * Adapter: data?.items ?? []  (EstimateListResult is NOT bare array)
 */

type Filter = "all" | "in_flight" | "done";

const FILTERS: ReadonlyArray<{ value: Filter; label: string }> = [
  { value: "all", label: "All" },
  { value: "in_flight", label: "In flight" },
  { value: "done", label: "Done" },
];

export default function EstimatesPage() {
  const qc = useQueryClient();
  const { data, isLoading, error, refetch, dataUpdatedAt } = useListEstimates();

  const [filter, setFilter] = React.useState<Filter>("all");
  const [uploadOpen, setUploadOpen] = React.useState(false);

  // Envelope adapter: EstimateListResult has .items, not a bare array.
  const allItems = React.useMemo(() => data?.items ?? [], [data?.items]);

  const visible = React.useMemo(() => {
    if (filter === "all") return allItems;
    if (filter === "done")
      return allItems.filter((it) => it.status_hint === "published");
    return allItems.filter((it) => it.status_hint !== "published");
  }, [allItems, filter]);

  // Pull-to-refresh.
  const touchStart = React.useRef<{ y: number; top: boolean } | null>(null);
  const onTouchStart = (e: React.TouchEvent) => {
    const el = e.currentTarget as HTMLDivElement;
    touchStart.current = { y: e.touches[0].clientY, top: el.scrollTop <= 0 };
  };
  const onTouchEnd = (e: React.TouchEvent) => {
    const s = touchStart.current;
    if (!s) return;
    const dy = e.changedTouches[0].clientY - s.y;
    if (s.top && dy > 80) {
      void qc.invalidateQueries({ queryKey: ["estimates"] });
      void refetch();
    }
    touchStart.current = null;
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
            className="-mr-1 inline-flex min-h-[36px] items-center gap-1 rounded-full bg-accent/10 px-3 py-1 text-callout font-medium text-accent active:opacity-70 no-tap-highlight"
          >
            <Plus className="h-4 w-4" strokeWidth={2.25} />
            <span>New</span>
          </button>
        }
      />

      <div
        className="mx-auto w-full max-w-[708px] px-4 pt-3 pb-8 md:max-w-4xl md:px-8"
        onTouchStart={onTouchStart}
        onTouchEnd={onTouchEnd}
      >
        {/* Segmented filter — pill tabs matching Lovable redesign */}
        <div
          role="tablist"
          aria-label="Filter estimates by status"
          className="mb-3 flex gap-1 rounded-xl bg-bg-elevated p-1"
        >
          {FILTERS.map((f) => {
            const active = filter === f.value;
            return (
              <button
                key={f.value}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setFilter(f.value)}
                className={cn(
                  "flex-1 rounded-lg py-2 text-caption-1 font-semibold transition-all",
                  active
                    ? "bg-accent/15 text-accent shadow-sm"
                    : "text-label-secondary",
                )}
              >
                {f.label}
              </button>
            );
          })}
        </div>

        {error && (
          <div className="mb-3 rounded-xl border border-danger/30 bg-danger/10 p-3 text-callout text-danger">
            Couldn&apos;t load your estimates. Pull down to retry.
          </div>
        )}

        {isLoading && allItems.length === 0 ? (
          <SkeletonRows />
        ) : visible.length === 0 ? (
          <EmptyState filter={filter} onNew={() => setUploadOpen(true)} />
        ) : (
          <ul
            className="divide-y divide-separator/40 overflow-hidden rounded-2xl border border-hairline bg-bg-elevated"
            aria-label="Estimates"
          >
            {visible.map((item) => (
              <li key={item.upload_id}>
                <EstimateRow item={item} />
              </li>
            ))}
          </ul>
        )}

        {allItems.length > 0 && (
          <div className="px-1 pb-6 pt-3 text-footnote text-label-tertiary">
            Last refreshed {formatLastRefreshed(dataUpdatedAt)}
          </div>
        )}
      </div>

      <UploadEstimateSheet open={uploadOpen} onOpenChange={setUploadOpen} />
    </MobileShell>
  );
}

/* ── Estimate row ───────────────────────────────────────────────────────── */

function EstimateRow({ item }: { item: EstimateListItem }) {
  const isPublished = item.status_hint === "published";
  const Icon = isPublished ? Calculator : Ruler;

  // Use prod token equivalences per LOVABLE_PORT_CONTRACT "Known token equivalences".
  // success/info tokens exist in prod; emerald/sky inline colors are NOT used.
  const iconTone = isPublished
    ? "bg-success/15 text-success"
    : "bg-info/15 text-info";

  // Tap target: published packages → documents detail; in-flight → estimates progress.
  const href =
    isPublished && item.package_document_id
      ? `/documents/${encodeURIComponent(item.package_document_id)}`
      : `/estimates/${encodeURIComponent(item.upload_id)}`;

  const dateAgo = formatRelative(item.created_at);

  return (
    <a
      href={href}
      className="flex w-full items-center gap-3 px-4 py-3 text-left no-tap-highlight transition-transform active:scale-[0.995]"
      aria-label={`Estimate: ${item.project_label}`}
    >
      <div
        className={cn(
          "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
          iconTone,
        )}
      >
        <Icon className="h-4 w-4" strokeWidth={1.75} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-callout font-semibold text-label-primary">
          {item.project_label}
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-1 text-footnote">
          <span className="text-label-primary">
            {item.aace_class
              ? `Class ${item.aace_class} estimate`
              : "Estimate"}
          </span>
          <span className="text-label-tertiary">·</span>
          <StatusInline isPublished={isPublished} />
          {dateAgo && (
            <>
              <span className="text-label-tertiary">·</span>
              <span className="text-label-tertiary">{dateAgo}</span>
            </>
          )}
        </div>
      </div>
      <div className="flex flex-col items-end gap-0.5">
        {isPublished && typeof item.total_usd === "number" ? (
          <span className="text-callout font-semibold tabular-nums text-label-primary">
            {formatUsd(item.total_usd)}
          </span>
        ) : (
          <span className="text-footnote text-label-tertiary">
            {isPublished ? "—" : "In flight"}
          </span>
        )}
        <ChevronRight className="h-4 w-4 text-label-quaternary" />
      </div>
    </a>
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

/* ── Empty states ───────────────────────────────────────────────────────── */

function EmptyState({
  filter,
  onNew,
}: {
  filter: Filter;
  onNew: () => void;
}) {
  if (filter === "in_flight") {
    return (
      <div className="flex flex-col items-center px-6 py-12 text-center">
        <Loader2 className="mb-3 h-8 w-8 text-label-quaternary" />
        <div className="text-title-3 text-label-primary">
          Nothing in flight.
        </div>
        <div className="mt-1 max-w-[28ch] text-body text-label-secondary">
          When you start an estimate from drawings, it&apos;ll show up here
          while it runs.
        </div>
      </div>
    );
  }
  if (filter === "done") {
    return (
      <div className="flex flex-col items-center px-6 py-12 text-center">
        <CheckCircle2 className="mb-3 h-8 w-8 text-label-quaternary" />
        <div className="text-title-3 text-label-primary">
          No published estimates yet.
        </div>
        <div className="mt-1 max-w-[32ch] text-body text-label-secondary">
          Approved cost &amp; schedule packages will collect here once they ship.
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <span
        className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/10 text-accent"
        aria-hidden="true"
      >
        <Calculator className="h-7 w-7" strokeWidth={1.5} />
      </span>
      <div className="text-title-3 text-label-primary">No estimates yet.</div>
      <div className="mt-1 max-w-[28ch] text-body text-label-secondary">
        Tap + New to upload drawings and generate your first cost + schedule
        estimate.
      </div>
      <button
        type="button"
        onClick={onNew}
        className="mt-5 inline-flex h-11 items-center gap-1.5 rounded-md bg-accent px-4 text-headline text-white active:opacity-85 no-tap-highlight"
      >
        <Plus className="h-4 w-4" strokeWidth={2.25} />
        New estimate
        <ChevronRight className="h-4 w-4 opacity-80" />
      </button>
    </div>
  );
}

/* ── Skeleton ───────────────────────────────────────────────────────────── */

function SkeletonRows() {
  return (
    <ul className="divide-y divide-separator/40 overflow-hidden rounded-2xl border border-hairline bg-bg-elevated">
      {Array.from({ length: 4 }).map((_, i) => (
        <li key={i} className="flex min-h-[56px] items-center gap-3 px-4 py-3">
          <span className="h-9 w-9 shrink-0 rounded-lg bg-bg-tertiary" />
          <div className="flex-1 space-y-1.5">
            <span className="block h-3.5 w-2/3 rounded-sm bg-bg-tertiary" />
            <span className="block h-3 w-5/6 rounded-sm bg-bg-tertiary" />
          </div>
        </li>
      ))}
    </ul>
  );
}

/* ── Helpers ────────────────────────────────────────────────────────────── */

function formatUsd(n: number): string {
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 10_000) return `$${(n / 1000).toFixed(0)}K`;
  if (Math.abs(n) >= 1000) return `$${(n / 1000).toFixed(1)}K`;
  return `$${Math.round(n).toLocaleString()}`;
}

function formatRelative(iso: string): string {
  const ts = +new Date(iso);
  if (!Number.isFinite(ts)) return "";
  const s = Math.max(1, Math.floor((Date.now() - ts) / 1000));
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  const mo = Math.floor(d / 30);
  return `${mo}mo ago`;
}

function formatLastRefreshed(ts: number | undefined): string {
  if (!ts) return "just now";
  const s = Math.max(1, Math.floor((Date.now() - ts) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return `${h}h ago`;
}
