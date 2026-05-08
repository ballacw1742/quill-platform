"use client";

import * as React from "react";
import { FileText, Search, SlidersHorizontal, X } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { Input } from "@/components/ui/input";
import { DocumentRow } from "@/components/documents/DocumentRow";
import { useDocuments, useSearchDocuments } from "@/lib/api";
import {
  DOCUMENT_FILTER_OPTIONS,
  filterToArtifactType,
  type DocumentFilterValue,
} from "@/lib/document-meta";

/**
 * /documents — Phase D.2 main screen.
 *
 * Layout (top → bottom), per DOCUMENTS_SPEC.md §"UI — `/documents` tab" and
 * MOBILE_UX_SPEC §"List rows":
 *
 *   1. TopBar: "Documents" title, right-side search + filter icons.
 *   2. (optional) expanded search input.
 *   3. SegmentedControl: 6 segments — All / Status / Process / Analyses /
 *      Comms / Knowledge.
 *   4. Pull-to-refresh container (matches /queue).
 *   5. List of DocumentRow items (or search results when search is active).
 *   6. Empty state per the COPY_GUIDE voice.
 *
 * Filters and search are mutually-aware: typing into the search bar shifts
 * the list to FTS results from `useSearchDocuments`. The segmented filter
 * still applies (we filter results client-side by artifact_type).
 *
 * Filter sheet (gear icon) is a forward hook — Phase D.2 ships only the
 * search + segmented filter; richer multi-axis filtering can land later.
 */
export default function DocumentsPage() {
  const qc = useQueryClient();

  const [filter, setFilter] = React.useState<DocumentFilterValue>("all");
  const [searchOpen, setSearchOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");

  // Debounce the search input so we don't hammer the FTS endpoint on every
  // keystroke. 200ms is fast enough to feel live, slow enough to coalesce.
  const debouncedSearch = useDebouncedValue(search, 200);

  const listQuery = useDocuments(
    { artifact_type: filterToArtifactType(filter), limit: 100 },
    { enabled: debouncedSearch.trim().length === 0 },
  );
  const searchQuery = useSearchDocuments(debouncedSearch);

  const activeMode: "list" | "search" =
    debouncedSearch.trim().length > 0 ? "search" : "list";

  const rows = React.useMemo(() => {
    if (activeMode === "search") {
      const items = searchQuery.data?.items ?? [];
      // Apply the segmented filter client-side on top of FTS results so the
      // chosen tab stays meaningful while searching.
      const wanted = filterToArtifactType(filter);
      return wanted ? items.filter((d) => d.artifact_type === wanted) : items;
    }
    return listQuery.data?.items ?? [];
  }, [activeMode, searchQuery.data, listQuery.data, filter]);

  const isLoading =
    activeMode === "search" ? searchQuery.isLoading : listQuery.isLoading;
  const error = activeMode === "search" ? searchQuery.error : listQuery.error;

  // Pull-to-refresh — same gesture pattern as /queue.
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
    }
    onTouchStart.current = null;
  };

  return (
    <MobileShell>
      <TopBar
        title="Documents"
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
              {searchOpen ? (
                <X className="h-5 w-5" />
              ) : (
                <Search className="h-5 w-5" />
              )}
            </button>
            <button
              type="button"
              aria-label="Filter"
              // Filter sheet is a future enhancement (Phase D.3). For now,
              // tapping focuses the segmented control area for parity.
              onClick={() => {
                if (typeof window !== "undefined") {
                  const el = document.getElementById("documents-segmented");
                  el?.scrollIntoView({ behavior: "smooth", block: "start" });
                }
              }}
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
              placeholder="Search documents…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-11 rounded-md bg-bg-elevated border-transparent text-body"
              aria-label="Search documents"
            />
          </div>
        )}

        <div id="documents-segmented" className="px-4 pt-2 pb-3 bg-bg">
          <SegmentedControl
            value={filter}
            onChange={setFilter}
            options={DOCUMENT_FILTER_OPTIONS}
            ariaLabel="Filter documents by type"
          />
        </div>

        <div className="flex-1 bg-bg-elevated">
          {error && (
            <ErrorBanner
              message="Couldn't load documents. Try again."
              onRetry={() => {
                if (activeMode === "search") void searchQuery.refetch();
                else void listQuery.refetch();
              }}
            />
          )}
          {isLoading ? (
            <SkeletonRows />
          ) : rows.length === 0 ? (
            <DocumentsEmptyState mode={activeMode} query={debouncedSearch} />
          ) : (
            <ul
              className="divide-y divide-separator/40 bg-bg-tertiary"
              aria-label={
                activeMode === "search" ? "Search results" : "Documents"
              }
            >
              {rows.map((doc, i) => (
                <li key={doc.id}>
                  <DocumentRow
                    doc={doc}
                    showSnippet={activeMode === "search"}
                    hideDivider={i === rows.length - 1}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </MobileShell>
  );
}

/* ── Helpers ─────────────────────────────────────────────────────────────── */

function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(t);
  }, [value, delayMs]);
  return debounced;
}

function SkeletonRows() {
  return (
    <ul
      className="divide-y divide-separator/40 bg-bg-tertiary"
      aria-label="Loading documents"
    >
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

function DocumentsEmptyState({
  mode,
  query,
}: {
  mode: "list" | "search";
  query: string;
}) {
  if (mode === "search") {
    return (
      <EmptyState
        icon={<Search />}
        title="No matches."
        subtitle={
          query
            ? `Nothing matched "${query}". Try a shorter or different phrase.`
            : "Type to search."
        }
      />
    );
  }
  return (
    <EmptyState
      icon={<FileText />}
      title="No documents yet."
      subtitle="When Quill helpers produce status updates, SOPs, or other artifacts, they'll show up here."
    />
  );
}
