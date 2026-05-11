"use client";

import * as React from "react";
import { FileText, Plus } from "lucide-react";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { ListRow } from "@/components/ui/list-row";
import { UploadContractSheet } from "@/components/contracts/UploadContractSheet";
import { useContractsList } from "@/lib/api";
import type { ContractListItem } from "@/lib/schemas";
import { cn } from "@/lib/utils";

// ── Filter segments ────────────────────────────────────────────────────────
type FilterValue = "all" | "extracted" | "reviewed" | "drafted";

const FILTER_OPTIONS: { label: string; value: FilterValue }[] = [
  { label: "All", value: "all" },
  { label: "Extracted", value: "extracted" },
  { label: "Reviewed", value: "reviewed" },
  { label: "Drafted", value: "drafted" },
];

// ── Helpers ───────────────────────────────────────────────────────────────
function relativeTime(date: string | Date): string {
  const d = typeof date === "string" ? new Date(date) : date;
  const diffMs = Date.now() - d.getTime();
  const diffMins = Math.round(diffMs / 60_000);
  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHrs = Math.round(diffMins / 60);
  if (diffHrs < 24) return `${diffHrs}h ago`;
  const diffDays = Math.round(diffHrs / 24);
  if (diffDays < 30) return `${diffDays}d ago`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function formatUSD(v: number | null | undefined): string {
  if (v == null) return "";
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(v);
}

function contractTypeLabel(t: string | null | undefined): string {
  if (!t) return "";
  return t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function statusColor(status: string): string {
  switch (status) {
    case "reviewed": return "text-green-700 bg-green-50";
    case "extracted": return "text-blue-700 bg-blue-50";
    case "reviewing": return "text-amber-700 bg-amber-50";
    case "failed": return "text-red-700 bg-red-50";
    default: return "text-label-tertiary bg-bg-elevated";
  }
}

function ContractChip({ contract }: { contract: ContractListItem }) {
  if (contract.total_value_usd) {
    return (
      <span className="text-caption font-medium text-label-secondary">
        {formatUSD(contract.total_value_usd)}
      </span>
    );
  }
  return null;
}

function ContractRow({ contract }: { contract: ContractListItem }) {
  const title =
    contract.project_label ||
    `Contract ${contract.upload_id.slice(0, 8)}`;
  const typeStr = contractTypeLabel(contract.contract_type);
  const ago = contract.created_at ? relativeTime(contract.created_at) : "";

  const subtitle = (
    <span className="flex items-center gap-1.5 flex-wrap">
      {typeStr && (
        <span className="text-caption text-label-tertiary">{typeStr}</span>
      )}
      <span
        className={cn(
          "text-caption rounded px-1 py-0.5 font-medium",
          statusColor(contract.status),
        )}
      >
        {contract.status}
      </span>
      <span className="text-caption text-label-tertiary">{ago}</span>
    </span>
  );

  return (
    <ListRow
      icon={<FileText className="h-5 w-5" />}
      iconTone="accent"
      title={title}
      subtitle={subtitle}
      chip={<ContractChip contract={contract} />}
      href={`/contracts/${contract.upload_id}`}
    />
  );
}

// ── Page ──────────────────────────────────────────────────────────────────
export default function ContractsPage() {
  const [filter, setFilter] = React.useState<FilterValue>("all");
  const [uploadOpen, setUploadOpen] = React.useState(false);

  const statusParam = filter === "all" ? undefined : filter;
  const { data, isLoading, error } = useContractsList({ status: statusParam, limit: 50 });

  const items = data?.items ?? [];

  return (
    <MobileShell>
      <TopBar
        title="Contracts"
        right={
          <button
            type="button"
            onClick={() => setUploadOpen(true)}
            className="flex items-center gap-1 rounded-lg bg-accent px-3 py-2 min-h-[36px] text-caption font-semibold text-white active:bg-accent/80 no-tap-highlight"
            aria-label="Upload new contract"
          >
            <Plus className="h-4 w-4" />
            New
          </button>
        }
      />

      <div className="px-4 pt-3 pb-2">
        <SegmentedControl
          options={FILTER_OPTIONS}
          value={filter}
          onChange={(v) => setFilter(v as FilterValue)}
        />
      </div>

      {filter === "drafted" && (
        <div className="px-4 py-6">
          <EmptyState
            icon={<FileText className="h-8 w-8 text-label-tertiary" />}
            title="No drafted contracts yet"
            subtitle="Contract drafting is coming in a future sprint."
          />
        </div>
      )}

      {filter !== "drafted" && (
        <div className="flex-1 overflow-y-auto">
          {error && (
            <div className="px-4 pt-2">
              <ErrorBanner message="Failed to load contracts. Pull to retry." />
            </div>
          )}

          {isLoading && (
            <div className="px-4 py-8 text-center text-callout text-label-secondary">
              Loading…
            </div>
          )}

          {!isLoading && !error && items.length === 0 && (
            <div className="px-4 py-8">
              <EmptyState
                icon={<FileText className="h-8 w-8 text-label-tertiary" />}
                title={
                  filter === "all"
                    ? "No contracts yet"
                    : `No ${filter} contracts`
                }
                subtitle={
                  filter === "all"
                    ? "Upload a contract to get started."
                    : `No contracts with status "${filter}".`
                }
                action={
                  filter === "all" ? (
                    <button
                      type="button"
                      onClick={() => setUploadOpen(true)}
                      className="rounded-xl border border-accent px-4 py-2 min-h-[44px] text-callout font-medium text-accent active:bg-accent/5 no-tap-highlight"
                    >
                      Upload Contract
                    </button>
                  ) : undefined
                }
              />
            </div>
          )}

          {!isLoading && items.length > 0 && (
            <div className="px-4">
              {items.map((c) => (
                <ContractRow key={c.upload_id} contract={c} />
              ))}
            </div>
          )}
        </div>
      )}

      <UploadContractSheet open={uploadOpen} onOpenChange={setUploadOpen} />
    </MobileShell>
  );
}
