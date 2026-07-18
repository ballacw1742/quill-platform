"use client";

import * as React from "react";
import { FileText, Plus, PenLine } from "lucide-react";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { ContractRow } from "@/components/contracts/ContractRow";
import { UploadContractSheet } from "@/components/contracts/UploadContractSheet";
import { DraftContractSheet } from "@/components/contracts/DraftContractSheet";
import { useContractsList } from "@/lib/api";
import { cn } from "@/lib/utils";

// ── Filter segments ────────────────────────────────────────────────────────
type FilterValue = "all" | "extracted" | "reviewed" | "drafted";

const FILTERS: { label: string; value: FilterValue }[] = [
  { label: "All", value: "all" },
  { label: "Extracted", value: "extracted" },
  { label: "Reviewed", value: "reviewed" },
  { label: "Drafted", value: "drafted" },
];

// ── Page ──────────────────────────────────────────────────────────────────
export default function ContractsPage() {
  const [filter, setFilter] = React.useState<FilterValue>("all");
  const [uploadOpen, setUploadOpen] = React.useState(false);
  const [draftOpen, setDraftOpen] = React.useState(false);

  // For "drafted" filter, use source=drafted rather than status
  const statusParam = filter === "all" || filter === "drafted" ? undefined : filter;
  const sourceParam = filter === "drafted" ? "drafted" : undefined;
  const { data, isLoading, error } = useContractsList({ status: statusParam, source: sourceParam, limit: 50 } as any);

  const items = data?.items ?? [];

  return (
    <MobileShell>
      <TopBar
        title="Contracts"
        right={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setDraftOpen(true)}
              className="flex h-9 w-9 items-center justify-center rounded-full border border-accent text-accent active:bg-accent/5 no-tap-highlight"
              aria-label="Draft a new contract"
              title="Draft"
            >
              <PenLine className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => setUploadOpen(true)}
              className="flex h-9 w-9 items-center justify-center rounded-full bg-accent text-white active:bg-accent/80 no-tap-highlight"
              aria-label="Upload new contract"
              title="Upload"
            >
              <Plus className="h-4 w-4" />
            </button>
          </div>
        }
      />

      <div className="mx-auto w-full max-w-[708px] px-4 pt-3 md:max-w-4xl md:px-8">
        {/* Filter tab bar — Lovable style: bg-bg-elevated pill, active bg-chrome shadow-sm */}
        <div
          role="tablist"
          aria-label="Contract filter"
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
                  "flex-1 rounded-lg py-2 text-caption font-semibold transition-all duration-tap ease-ios no-tap-highlight",
                  active
                    ? "bg-bg-primary text-label-primary shadow-card"
                    : "text-label-secondary active:bg-bg-primary/50",
                )}
              >
                {f.label}
              </button>
            );
          })}
        </div>

        {/* Error */}
        {error && (
          <div className="mb-3 rounded-xl border border-danger/30 bg-danger/10 p-3 text-callout text-danger">
            Failed to load contracts.
          </div>
        )}

        {/* Skeleton loading */}
        {isLoading &&
          Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="mb-2 h-20 animate-pulse rounded-2xl border border-hairline bg-bg-elevated"
            />
          ))}

        {/* Empty state */}
        {!isLoading && !error && items.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-4 px-6 pt-16">
            <FileText className="h-12 w-12 text-label-tertiary" />
            <div className="text-center">
              <p className="mb-1 text-body font-semibold text-label-primary">
                {filter === "all" ? "No contracts yet" : `No ${filter} contracts`}
              </p>
              <p className="text-callout text-label-secondary">
                {filter === "all"
                  ? "Upload an executed contract or start a new draft."
                  : "Nothing here yet — try a different filter."}
              </p>
            </div>
            {filter === "all" && (
              <button
                type="button"
                onClick={() => setUploadOpen(true)}
                className="mt-2 flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 text-callout font-semibold text-white no-tap-highlight active:bg-accent/80"
              >
                <Plus className="h-4 w-4" />
                Upload contract
              </button>
            )}
          </div>
        )}

        {/* Contract list */}
        {!isLoading && items.length > 0 && (
          <div className="pt-1">
            {items.map((c) => (
              <ContractRow key={c.upload_id} contract={c} />
            ))}
          </div>
        )}
      </div>

      <UploadContractSheet open={uploadOpen} onOpenChange={setUploadOpen} />
      <DraftContractSheet open={draftOpen} onOpenChange={setDraftOpen} />
    </MobileShell>
  );
}
