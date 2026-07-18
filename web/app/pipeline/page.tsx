"use client";

/**
 * /pipeline -- Sales Pipeline (Lovable redesign port)
 *
 * Lovable source: quill-platform-builder/src/routes/pipeline.tsx
 * Visual layer ported 1:1; real-data wiring kept from prod (lib/api.ts).
 * Token changes: shadow-sm -> shadow-card; color-name classes -> semantic tokens;
 *   text-green-400 -> text-success; text-red-400 -> text-danger; text-blue-400 -> text-info;
 *   text-purple-400 -> text-accent; text-warning -> text-warning.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { TrendingUp, Plus, X, Activity } from "lucide-react";
import { cn } from "@/lib/utils";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { DealCard } from "@/components/pipeline/DealCard";
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
  { key: "qualified",   label: "Qualified",   color: "text-info" },
  { key: "proposal",    label: "Proposal",    color: "text-accent" },
  { key: "negotiating", label: "Negotiating", color: "text-warning" },
  { key: "won",         label: "Won",         color: "text-success" },
  { key: "lost",        label: "Lost",        color: "text-danger" },
];

// ── Summary Stats ─────────────────────────────────────────────────────────────

function SummaryBar({ summary }: { summary: PipelineSummary }) {
  const stats = [
    { label: "Active Deals", value: String(summary.total_active_deals) },
    {
      label: "MW in Pipeline",
      value:
        summary.total_active_mw > 0
          ? `${summary.total_active_mw.toFixed(0)} MW`
          : "--",
    },
    {
      label: "Pipeline Value",
      value:
        summary.total_active_value_usd > 0
          ? `$${(summary.total_active_value_usd / 1_000_000).toFixed(1)}M`
          : "--",
    },
    {
      label: "Win Rate",
      value: summary.win_rate_pct != null ? `${summary.win_rate_pct}%` : "--",
    },
  ];

  return (
    <div
      className="grid gap-3 px-4 mb-4"
      style={{ gridTemplateColumns: `repeat(${stats.length}, minmax(0, 1fr))` }}
    >
      {stats.map((s) => (
        <div
          key={s.label}
          className="rounded-2xl px-3 py-3 text-center bg-chrome/80 border border-hairline"
        >
          <p className="text-title-3 font-bold text-label-primary tabular-nums">
            {s.value}
          </p>
          <p className="text-caption-2 text-label-secondary mt-0.5">{s.label}</p>
        </div>
      ))}
    </div>
  );
}

// ── Kanban Column ─────────────────────────────────────────────────────────────

function KanbanColumn({
  stage,
  deals,
  accountMap,
  onDealClick,
  onViewCustomer,
}: {
  stage: { key: string; label: string; color: string };
  deals: Deal[];
  accountMap: Record<string, string>;
  onDealClick: (id: string) => void;
  onViewCustomer: (accountId: string) => void;
}) {
  return (
    <div className="w-full rounded-2xl bg-bg-elevated shadow-card p-3 md:w-60 md:flex-none">
      <div className="flex items-center justify-between mb-3">
        <span
          className={cn(
            "text-footnote font-bold uppercase tracking-wide",
            stage.color,
          )}
        >
          {stage.label}
        </span>
        <span className="text-caption-2 text-label-tertiary font-medium bg-separator/20 rounded-full px-1.5 py-0.5">
          {deals.length}
        </span>
      </div>
      {deals.length === 0 ? (
        <p className="text-caption-2 text-label-quaternary italic text-center py-4">
          Empty
        </p>
      ) : (
        deals.map((d) => (
          <DealCard
            key={d.id}
            deal={d}
            accountName={accountMap[d.account_id]}
            onClick={() => onDealClick(d.id)}
            onViewCustomer={() => onViewCustomer(d.account_id)}
          />
        ))
      )}
    </div>
  );
}

// ── New Deal Modal ────────────────────────────────────────────────────────────

const inputCls =
  "w-full rounded-xl bg-bg-elevated shadow-card px-3 py-2.5 text-body text-label-primary placeholder:text-label-tertiary focus:outline-none focus:border-accent";

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-caption-1 text-label-secondary">{label}</span>
      {children}
    </label>
  );
}

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

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!accountName.trim() || !dealName.trim()) {
      setError("Account name and Deal name are required.");
      return;
    }
    try {
      const existing = accountsData?.items?.find(
        (a) => a.name.toLowerCase() === accountName.trim().toLowerCase(),
      );
      const accountId = existing
        ? existing.id
        : (
            await createAccount.mutateAsync({
              name: accountName.trim(),
              type: "prospect",
            })
          ).id;
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create deal");
    }
  }

  const isPending = createAccount.isPending || createDeal.isPending;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 backdrop-blur-sm sm:items-center">
      <div className="w-full max-w-lg rounded-t-2xl sm:rounded-2xl bg-chrome border border-hairline shadow-2xl pb-safe">
        <div className="flex items-center justify-between px-4 pt-4 pb-2 border-b border-hairline">
          <h2 className="text-headline font-semibold text-label-primary">
            New Deal
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-label-secondary active:text-label-primary"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3 px-4 py-4">
          {error && (
            <p className="text-caption-1 text-danger bg-danger/10 rounded-xl px-3 py-2">
              {error}
            </p>
          )}
          <Field label="Account Name *">
            <input
              className={inputCls}
              placeholder="Acme Corp"
              value={accountName}
              onChange={(e) => setAccountName(e.target.value)}
              required
            />
          </Field>
          <Field label="Deal Name *">
            <input
              className={inputCls}
              placeholder="150MW AI Training Cluster"
              value={dealName}
              onChange={(e) => setDealName(e.target.value)}
              required
            />
          </Field>
          <Field label="Stage">
            <select
              className={inputCls}
              value={stage}
              onChange={(e) => setStage(e.target.value)}
            >
              {DEAL_STAGES.map((s) => (
                <option key={s} value={s}>
                  {s.charAt(0).toUpperCase() + s.slice(1)}
                </option>
              ))}
            </select>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="MW Required">
              <input
                type="number"
                className={inputCls}
                placeholder="150"
                value={mwRequired}
                onChange={(e) => setMwRequired(e.target.value)}
              />
            </Field>
            <Field label="Workload Type">
              <select
                className={inputCls}
                value={workloadType}
                onChange={(e) => setWorkloadType(e.target.value)}
              >
                <option value="">Select...</option>
                {WORKLOAD_TYPES.map((w) => (
                  <option key={w} value={w}>
                    {w}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Expected Close">
            <input
              type="date"
              className={inputCls}
              value={expectedClose}
              onChange={(e) => setExpectedClose(e.target.value)}
            />
          </Field>
          <Field label="Notes">
            <textarea
              rows={3}
              className={cn(inputCls, "resize-none")}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </Field>
          <button
            type="submit"
            disabled={isPending}
            className={cn(
              "mt-2 w-full rounded-xl py-3 text-body font-semibold bg-accent text-primary-foreground",
              isPending && "opacity-40 cursor-not-allowed",
            )}
          >
            {isPending ? "Creating..." : "Create Deal"}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

function PipelinePageInner() {
  const router = useRouter();
  const [showNewDeal, setShowNewDeal] = React.useState(false);

  const { data: dealsData, error: dealsError, isLoading: dealsLoading } = useDeals();
  const { data: summary } = usePipelineSummary();
  const { data: accountsData } = useAccounts();

  // Envelope adapter: useDeals -> DealListPage {items, total}
  const accountMap = React.useMemo(() => {
    const map: Record<string, string> = {};
    accountsData?.items?.forEach((a) => { map[a.id] = a.name; });
    return map;
  }, [accountsData]);

  // Envelope adapter: useDeals -> DealListPage {items, total}
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

      <div className="flex-1 overflow-y-auto pt-2 pb-[calc(env(safe-area-inset-bottom)+80px)]">
        {dealsError && (
          <div className="px-4 mb-3">
            <div className="rounded-2xl bg-danger/10 border border-danger/20 px-4 py-3 text-caption-1 text-danger">
              Failed to load pipeline data.
            </div>
          </div>
        )}

        {summary && <SummaryBar summary={summary} />}

        <div className="px-4 mt-3 mb-3 flex items-center gap-2">
          <Activity className="h-4 w-4 text-label-tertiary" />
          <span className="text-footnote font-semibold text-label-secondary uppercase tracking-wide">
            Deal Board
          </span>
          {dealsLoading && (
            <span className="text-caption-2 text-label-tertiary">Loading...</span>
          )}
        </div>

        <div className="flex flex-col gap-3 px-4 pb-3 md:flex-row md:overflow-x-auto md:no-scrollbar">
          {STAGES.map((stage) => (
            <KanbanColumn
              key={stage.key}
              stage={stage}
              deals={dealsByStage[stage.key] ?? []}
              accountMap={accountMap}
              onDealClick={(id) => router.push(`/pipeline/deals/${id}`)}
              onViewCustomer={(accountId) => router.push(`/customers/${accountId}`)}
            />
          ))}
        </div>
      </div>

      {/* FAB */}
      <button
        type="button"
        onClick={() => setShowNewDeal(true)}
        className={cn(
          "fixed bottom-[calc(env(safe-area-inset-bottom)+16px)] right-5 z-40",
          "w-14 h-14 rounded-full bg-accent shadow-card",
          "flex items-center justify-center",
          "transition-transform active:scale-95",
        )}
        aria-label="New Deal"
      >
        <Plus className="h-6 w-6 text-primary-foreground" />
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

export default function PipelinePage() {
  return (
    <ErrorBoundary moduleName="Pipeline">
      <PipelinePageInner />
    </ErrorBoundary>
  );
}
