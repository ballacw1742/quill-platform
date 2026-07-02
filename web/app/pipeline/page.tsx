"use client";

/**
 * /pipeline — Sales & Pipeline (Sprint 1B)
 *
 * Kanban board of deals by stage + pipeline summary stats.
 * Design: dark Quill theme, iOS-style cards, accent blue #0A84FF.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { TrendingUp, Plus, X, ChevronRight, Activity } from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { ErrorBanner } from "@/components/ui/error-banner";
import {
  useDeals,
  usePipelineSummary,
  useCreateDeal,
  useCreateAccount,
  useAccounts,
} from "@/lib/api";
import type { Deal, PipelineSummary } from "@/lib/schemas";
import { DEAL_STAGES, WORKLOAD_TYPES } from "@/lib/schemas";

// ── Stage config ──────────────────────────────────────────────────────────────

const STAGES: { key: string; label: string; color: string }[] = [
  { key: "prospect",    label: "Prospect",    color: "text-label-secondary" },
  { key: "qualified",   label: "Qualified",   color: "text-blue-400" },
  { key: "proposal",    label: "Proposal",    color: "text-purple-400" },
  { key: "negotiating", label: "Negotiating", color: "text-orange-400" },
  { key: "won",         label: "Won",         color: "text-green-400" },
  { key: "lost",        label: "Lost",        color: "text-red-400" },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatValue(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(0)}M ARR`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K ARR`;
  return `$${v.toFixed(0)}`;
}

function formatMW(v: number | null | undefined): string {
  if (v == null) return "";
  return `${v.toFixed(0)} MW`;
}

function probColor(pct: number | null | undefined): string {
  if (pct == null) return "text-label-tertiary bg-bg-elevated";
  if (pct >= 70) return "text-green-400 bg-green-400/10";
  if (pct >= 40) return "text-yellow-400 bg-yellow-400/10";
  return "text-label-tertiary bg-bg-elevated";
}

function isOverdue(dateStr: string | null | undefined): boolean {
  if (!dateStr) return false;
  return new Date(dateStr) < new Date();
}

// ── Deal Card ─────────────────────────────────────────────────────────────────

function DealCard({ deal, accountName, onClick }: {
  deal: Deal;
  accountName?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full text-left rounded-2xl p-3 mb-2",
        "bg-chrome/80 border border-separator/40",
        "backdrop-blur-sm",
        "transition-all active:scale-[0.98] hover:border-separator/80",
        "shadow-sm shadow-black/10",
      )}
    >
      {/* Account name */}
      {accountName && (
        <p className="text-caption-1 font-bold text-label-primary truncate mb-0.5">{accountName}</p>
      )}
      {/* Deal name */}
      <p className="text-caption-2 text-label-secondary truncate">{deal.name}</p>

      {/* Badges row */}
      <div className="flex items-center flex-wrap gap-1 mt-2">
        {deal.mw_required != null && (
          <span className="text-caption-2 font-semibold text-accent bg-accent/10 rounded-full px-1.5 py-0.5">
            {formatMW(deal.mw_required)}
          </span>
        )}
        {deal.value_usd != null && (
          <span className="text-caption-2 text-label-secondary">
            {formatValue(deal.value_usd)}
          </span>
        )}
        {deal.probability_pct != null && (
          <span className={cn("text-caption-2 font-semibold rounded-full px-1.5 py-0.5", probColor(deal.probability_pct))}>
            {deal.probability_pct}%
          </span>
        )}
        {deal.expected_close && (
          <span className={cn(
            "text-caption-2 rounded-full px-1.5 py-0.5",
            isOverdue(deal.expected_close)
              ? "text-red-400 bg-red-400/10 font-semibold"
              : "text-label-tertiary",
          )}>
            {deal.expected_close}
          </span>
        )}
      </div>
    </button>
  );
}

// ── Kanban Column ─────────────────────────────────────────────────────────────

function KanbanColumn({ stage, deals, accountMap, onDealClick }: {
  stage: { key: string; label: string; color: string };
  deals: Deal[];
  accountMap: Record<string, string>;
  onDealClick: (id: string) => void;
}) {
  return (
    <div
      className="flex-none rounded-2xl bg-bg-elevated/60 border border-separator/30 p-3"
      style={{ minWidth: 200, width: 220 }}
    >
      <div className="flex items-center justify-between mb-3">
        <span className={cn("text-footnote font-bold uppercase tracking-wide", stage.color)}>
          {stage.label}
        </span>
        <span className="text-caption-2 text-label-tertiary font-medium bg-separator/20 rounded-full px-1.5 py-0.5">
          {deals.length}
        </span>
      </div>
      {deals.length === 0 ? (
        <p className="text-caption-2 text-label-quaternary italic text-center py-4">Empty</p>
      ) : (
        deals.map((d) => (
          <DealCard
            key={d.id}
            deal={d}
            accountName={accountMap[d.account_id]}
            onClick={() => onDealClick(d.id)}
          />
        ))
      )}
    </div>
  );
}

// ── Summary Stats ─────────────────────────────────────────────────────────────

function SummaryBar({ summary }: { summary: PipelineSummary }) {
  const stats = [
    {
      label: "Active Deals",
      value: String(summary.total_active_deals),
    },
    {
      label: "MW in Pipeline",
      value: summary.total_active_mw > 0
        ? `${summary.total_active_mw.toFixed(0)} MW`
        : "—",
    },
    {
      label: "Pipeline Value",
      value: summary.total_active_value_usd > 0
        ? `$${(summary.total_active_value_usd / 1_000_000).toFixed(1)}M`
        : "—",
    },
    {
      label: "Win Rate",
      value: summary.win_rate_pct != null ? `${summary.win_rate_pct}%` : "—",
    },
  ];

  return (
    <div className="flex gap-3 px-4 mb-4 overflow-x-auto no-scrollbar">
      {stats.map((s) => (
        <div
          key={s.label}
          className={cn(
            "flex-none rounded-2xl px-4 py-3 text-center",
            "bg-chrome/80 border border-separator/40",
            "min-w-[100px]",
          )}
        >
          <p className="text-title-3 font-bold text-label-primary tabular-nums">{s.value}</p>
          <p className="text-caption-2 text-label-secondary mt-0.5">{s.label}</p>
        </div>
      ))}
    </div>
  );
}

// ── New Deal Modal ────────────────────────────────────────────────────────────

function NewDealModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const createAccount = useCreateAccount();
  const createDeal = useCreateDeal();
  const { data: accountsData } = useAccounts();

  const [accountName, setAccountName] = React.useState("");
  const [dealName, setDealName] = React.useState("");
  const [stage, setStage] = React.useState("prospect");
  const [mwRequired, setMwRequired] = React.useState("");
  const [workloadType, setWorkloadType] = React.useState("");
  const [expectedClose, setExpectedClose] = React.useState("");
  const [notes, setNotes] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  async function handleSubmit() {
    setError(null);
    if (!accountName.trim() || !dealName.trim()) {
      setError("Account name and Deal name are required.");
      return;
    }

    try {
      // Check if account exists, otherwise create it
      const existing = accountsData?.items?.find(
        (a) => a.name.toLowerCase() === accountName.trim().toLowerCase()
      );
      let accountId: string;
      if (existing) {
        accountId = existing.id;
      } else {
        const newAccount = await createAccount.mutateAsync({ name: accountName.trim(), type: "prospect" });
        accountId = newAccount.id;
      }

      const deal = await createDeal.mutateAsync({
        account_id: accountId,
        name: dealName.trim(),
        stage,
        mw_required: mwRequired ? parseFloat(mwRequired) : undefined,
        workload_type: workloadType || undefined,
        expected_close: expectedClose || undefined,
        notes: notes || undefined,
      });
      onCreated(deal.id);
    } catch (e: unknown) {
      const err = e as { message?: string };
      setError(err?.message ?? "Failed to create deal");
    }
  }

  const isPending = createAccount.isPending || createDeal.isPending;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg bg-chrome rounded-t-3xl p-6 pb-[calc(env(safe-area-inset-bottom)+24px)] overflow-y-auto max-h-[85vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="w-10 h-1 bg-separator/60 rounded-full mx-auto mb-5" />
        <div className="flex items-center justify-between mb-4">
          <p className="text-headline font-semibold text-label-primary">New Deal</p>
          <button type="button" onClick={onClose} className="text-label-tertiary hover:text-label-primary">
            <X className="h-5 w-5" />
          </button>
        </div>

        {error && <p className="text-caption-1 text-red-400 mb-3 bg-red-400/10 rounded-xl px-3 py-2">{error}</p>}

        {/* Account name */}
        <div className="mb-4">
          <label className="block text-footnote font-semibold text-label-secondary uppercase tracking-wide mb-1.5">
            Account Name *
          </label>
          <input
            value={accountName}
            onChange={(e) => setAccountName(e.target.value)}
            placeholder="Acme Corp"
            className="w-full bg-bg-elevated border border-separator/40 rounded-xl px-3 py-2.5 text-callout text-label-primary placeholder-label-quaternary outline-none focus:border-accent"
          />
          <p className="text-caption-2 text-label-tertiary mt-1">Creates new account if not found.</p>
        </div>

        {/* Deal name */}
        <div className="mb-4">
          <label className="block text-footnote font-semibold text-label-secondary uppercase tracking-wide mb-1.5">
            Deal Name *
          </label>
          <input
            value={dealName}
            onChange={(e) => setDealName(e.target.value)}
            placeholder="150MW AI Training Cluster"
            className="w-full bg-bg-elevated border border-separator/40 rounded-xl px-3 py-2.5 text-callout text-label-primary placeholder-label-quaternary outline-none focus:border-accent"
          />
        </div>

        {/* Stage */}
        <div className="mb-4">
          <label className="block text-footnote font-semibold text-label-secondary uppercase tracking-wide mb-1.5">
            Stage
          </label>
          <select
            value={stage}
            onChange={(e) => setStage(e.target.value)}
            className="w-full bg-bg-elevated border border-separator/40 rounded-xl px-3 py-2.5 text-callout text-label-primary outline-none focus:border-accent"
          >
            {DEAL_STAGES.map((s) => (
              <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
            ))}
          </select>
        </div>

        {/* MW Required */}
        <div className="mb-4">
          <label className="block text-footnote font-semibold text-label-secondary uppercase tracking-wide mb-1.5">
            MW Required
          </label>
          <input
            type="number"
            value={mwRequired}
            onChange={(e) => setMwRequired(e.target.value)}
            placeholder="150"
            className="w-full bg-bg-elevated border border-separator/40 rounded-xl px-3 py-2.5 text-callout text-label-primary placeholder-label-quaternary outline-none focus:border-accent"
          />
        </div>

        {/* Workload Type */}
        <div className="mb-4">
          <label className="block text-footnote font-semibold text-label-secondary uppercase tracking-wide mb-1.5">
            Workload Type
          </label>
          <select
            value={workloadType}
            onChange={(e) => setWorkloadType(e.target.value)}
            className="w-full bg-bg-elevated border border-separator/40 rounded-xl px-3 py-2.5 text-callout text-label-primary outline-none focus:border-accent"
          >
            <option value="">Select...</option>
            {WORKLOAD_TYPES.map((w) => (
              <option key={w} value={w}>{w}</option>
            ))}
          </select>
        </div>

        {/* Expected Close */}
        <div className="mb-4">
          <label className="block text-footnote font-semibold text-label-secondary uppercase tracking-wide mb-1.5">
            Expected Close Date
          </label>
          <input
            type="date"
            value={expectedClose}
            onChange={(e) => setExpectedClose(e.target.value)}
            className="w-full bg-bg-elevated border border-separator/40 rounded-xl px-3 py-2.5 text-callout text-label-primary outline-none focus:border-accent"
          />
        </div>

        {/* Notes */}
        <div className="mb-6">
          <label className="block text-footnote font-semibold text-label-secondary uppercase tracking-wide mb-1.5">
            Notes
          </label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            placeholder="Additional context..."
            className="w-full bg-bg-elevated border border-separator/40 rounded-xl px-3 py-2.5 text-callout text-label-primary placeholder-label-quaternary outline-none focus:border-accent resize-none"
          />
        </div>

        <button
          type="button"
          onClick={handleSubmit}
          disabled={isPending}
          className="w-full bg-accent text-white font-semibold text-callout rounded-2xl py-3 transition-opacity disabled:opacity-50"
        >
          {isPending ? "Creating..." : "Create Deal"}
        </button>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function PipelinePage() {
  const router = useRouter();
  const [showNewDeal, setShowNewDeal] = React.useState(false);

  const { data: dealsData, error: dealsError, isLoading: dealsLoading } = useDeals();
  const { data: summary } = usePipelineSummary();
  const { data: accountsData } = useAccounts();

  // Build accountId → name map for deal cards
  const accountMap = React.useMemo(() => {
    const map: Record<string, string> = {};
    accountsData?.items?.forEach((a) => { map[a.id] = a.name; });
    return map;
  }, [accountsData]);

  // Group deals by stage
  const dealsByStage = React.useMemo(() => {
    const map: Record<string, Deal[]> = {};
    STAGES.forEach((s) => { map[s.key] = []; });
    dealsData?.items?.forEach((d) => {
      if (map[d.stage]) map[d.stage].push(d);
    });
    return map;
  }, [dealsData]);

  return (
    <MobileShell>
      <TopBar
        title="Pipeline"
        right={<TrendingUp className="h-5 w-5 text-label-tertiary" />}
      />

      <div className="flex-1 overflow-y-auto pb-[calc(env(safe-area-inset-bottom)+80px)] pt-2">
        {dealsError && (
          <div className="px-4 mb-3">
            <ErrorBanner message="Failed to load pipeline data." />
          </div>
        )}

        {/* Summary stats */}
        {summary && <SummaryBar summary={summary} />}

        {/* Pipeline label */}
        <div className="px-4 mb-3 flex items-center gap-2">
          <Activity className="h-4 w-4 text-label-tertiary" />
          <span className="text-footnote font-semibold text-label-secondary uppercase tracking-wide">
            Deal Board
          </span>
          {dealsLoading && (
            <span className="text-caption-2 text-label-tertiary">Loading...</span>
          )}
        </div>

        {/* Kanban board — horizontal scroll */}
        <div
          className="flex gap-3 px-4 pb-3 overflow-x-auto no-scrollbar"
          style={{ scrollSnapType: "x mandatory" }}
        >
          {STAGES.map((stage) => (
            <KanbanColumn
              key={stage.key}
              stage={stage}
              deals={dealsByStage[stage.key] ?? []}
              accountMap={accountMap}
              onDealClick={(id) => router.push(`/pipeline/deals/${id}`)}
            />
          ))}
        </div>
      </div>

      {/* FAB */}
      <button
        type="button"
        onClick={() => setShowNewDeal(true)}
        className={cn(
          "fixed bottom-[calc(env(safe-area-inset-bottom)+72px)] right-5 z-40",
          "w-14 h-14 rounded-full bg-accent shadow-lg",
          "flex items-center justify-center",
          "transition-transform active:scale-95",
        )}
        aria-label="New Deal"
      >
        <Plus className="h-6 w-6 text-white" />
      </button>

      {showNewDeal && (
        <NewDealModal
          onClose={() => setShowNewDeal(false)}
          onCreated={(id) => {
            setShowNewDeal(false);
            router.push(`/pipeline/deals/${id}`);
          }}
        />
      )}
    </MobileShell>
  );
}
