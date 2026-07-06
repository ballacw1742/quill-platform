"use client";

/**
 * /finance — Finance Dashboard (Sprint 3A)
 *
 * Division 6: Makes the financial picture visible across the portfolio.
 * ARR from won deals, CapEx from equipment, project budgets, and AR aging.
 *
 * Design: dark Quill chrome, accent blue #0A84FF, matches /pipeline and /supply-chain.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  DollarSign,
  FileText,
  Plus,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import {
  useFinanceSummary,
  useArrBreakdown,
  useCapexBreakdown,
  useArAging,
  useInvoices,
  useCreateInvoice,
  useCreateBudgetLine,
  useUpdateInvoice,
} from "@/lib/api";
import type {
  FinanceSummary,
  ArrLine,
  CapexLine,
  ArAging,
  Invoice,
  AgingBucket,
} from "@/lib/schemas";
import { BUDGET_CATEGORIES } from "@/lib/schemas";

// ── Formatting helpers ─────────────────────────────────────────────────────────

function fmtUSD(v: number | null | undefined, compact = true): string {
  if (v == null) return "—";
  if (!compact) return `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  if (Math.abs(v) >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(1)}B`;
  if (Math.abs(v) >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
  return `$${v.toFixed(0)}`;
}

function fmtDate(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

// ── Status badge ──────────────────────────────────────────────────────────────

function InvoiceStatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    draft:     { label: "Draft",     cls: "text-zinc-400 bg-zinc-400/10" },
    sent:      { label: "Sent",      cls: "text-blue-400 bg-blue-400/10" },
    paid:      { label: "Paid",      cls: "text-green-400 bg-green-400/10" },
    overdue:   { label: "Overdue",   cls: "text-red-400 bg-red-400/10" },
    cancelled: { label: "Cancelled", cls: "text-zinc-500 bg-zinc-500/10" },
  };
  const { label, cls } = map[status] ?? { label: status, cls: "text-label-secondary bg-bg-elevated" };
  return (
    <span className={cn("inline-flex items-center rounded-md px-2 py-0.5 text-caption-1 font-medium", cls)}>
      {label}
    </span>
  );
}

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  color,
  icon: Icon,
}: {
  label: string;
  value: string;
  sub?: string;
  color: "green" | "blue" | "orange" | "red";
  icon: React.ElementType;
}) {
  const colorMap = {
    green:  { icon: "text-green-400",  bg: "bg-green-400/10" },
    blue:   { icon: "text-blue-400",   bg: "bg-blue-400/10"  },
    orange: { icon: "text-orange-400", bg: "bg-orange-400/10" },
    red:    { icon: "text-red-400",    bg: "bg-red-400/10"   },
  };
  const c = colorMap[color];
  return (
    <div className="rounded-2xl bg-bg-secondary border border-separator/30 p-4 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-caption-1 text-label-secondary">{label}</span>
        <span className={cn("flex h-7 w-7 items-center justify-center rounded-xl", c.bg)}>
          <Icon className={cn("h-4 w-4", c.icon)} strokeWidth={1.75} />
        </span>
      </div>
      <span className="text-title-2 font-semibold text-label-primary">{value}</span>
      {sub && <span className="text-caption-1 text-label-secondary">{sub}</span>}
    </div>
  );
}

// ── Section header ────────────────────────────────────────────────────────────

function SectionHeader({ title, count }: { title: string; count?: number }) {
  return (
    <div className="flex items-center justify-between px-4 pt-6 pb-2">
      <h2 className="text-headline font-semibold text-label-primary">{title}</h2>
      {count != null && (
        <span className="text-caption-1 text-label-tertiary">{count} item{count !== 1 ? "s" : ""}</span>
      )}
    </div>
  );
}

// ── CapEx bar ─────────────────────────────────────────────────────────────────

function CapexBar({ budget, forecast }: { budget: number | null | undefined; forecast: number | null | undefined }) {
  const b = budget ?? 0;
  const f = forecast ?? 0;
  if (b <= 0 && f <= 0) return null;
  const max = Math.max(b, f, 1);
  const overBudget = f > b;
  return (
    <div className="mt-2 space-y-1">
      <div className="flex gap-1 h-1.5 rounded-full overflow-hidden bg-bg-elevated">
        <div
          className="bg-blue-400/60 rounded-full"
          style={{ width: `${Math.min((b / max) * 100, 100)}%` }}
        />
      </div>
      <div className="flex gap-1 h-1.5 rounded-full overflow-hidden bg-bg-elevated">
        <div
          className={cn("rounded-full", overBudget ? "bg-red-400" : "bg-green-400")}
          style={{ width: `${Math.min((f / max) * 100, 100)}%` }}
        />
      </div>
    </div>
  );
}

// ── Modals ────────────────────────────────────────────────────────────────────

function NewInvoiceModal({ onClose }: { onClose: () => void }) {
  const createInvoice = useCreateInvoice();
  const [form, setForm] = React.useState({
    account_id: "",
    amount_usd: "",
    issue_date: new Date().toISOString().split("T")[0],
    due_date: "",
    notes: "",
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.amount_usd || !form.issue_date || !form.due_date) return;
    await createInvoice.mutateAsync({
      account_id: form.account_id || undefined,
      amount_usd: parseFloat(form.amount_usd),
      status: "draft",
      issue_date: form.issue_date as never,
      due_date: form.due_date as never,
      notes: form.notes || undefined,
    } as never);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-bg-secondary rounded-t-2xl border-t border-separator/60 p-6 pb-safe">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-headline font-semibold text-label-primary">New Invoice</h3>
          <button onClick={onClose} className="text-label-secondary active:opacity-60">
            <X className="h-5 w-5" />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-caption-1 text-label-secondary mb-1 block">Account</label>
            <input
              className="w-full rounded-xl bg-bg-elevated border border-separator/30 px-3 py-2 text-body text-label-primary"
              placeholder="Account name or ID"
              value={form.account_id}
              onChange={(e) => setForm(f => ({ ...f, account_id: e.target.value }))}
            />
          </div>
          <div>
            <label className="text-caption-1 text-label-secondary mb-1 block">Amount (USD) *</label>
            <input
              type="number"
              step="0.01"
              required
              className="w-full rounded-xl bg-bg-elevated border border-separator/30 px-3 py-2 text-body text-label-primary"
              placeholder="0.00"
              value={form.amount_usd}
              onChange={(e) => setForm(f => ({ ...f, amount_usd: e.target.value }))}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-caption-1 text-label-secondary mb-1 block">Issue Date *</label>
              <input
                type="date"
                required
                className="w-full rounded-xl bg-bg-elevated border border-separator/30 px-3 py-2 text-body text-label-primary"
                value={form.issue_date}
                onChange={(e) => setForm(f => ({ ...f, issue_date: e.target.value }))}
              />
            </div>
            <div>
              <label className="text-caption-1 text-label-secondary mb-1 block">Due Date *</label>
              <input
                type="date"
                required
                className="w-full rounded-xl bg-bg-elevated border border-separator/30 px-3 py-2 text-body text-label-primary"
                value={form.due_date}
                onChange={(e) => setForm(f => ({ ...f, due_date: e.target.value }))}
              />
            </div>
          </div>
          <div>
            <label className="text-caption-1 text-label-secondary mb-1 block">Notes</label>
            <textarea
              rows={2}
              className="w-full rounded-xl bg-bg-elevated border border-separator/30 px-3 py-2 text-body text-label-primary resize-none"
              placeholder="Optional"
              value={form.notes}
              onChange={(e) => setForm(f => ({ ...f, notes: e.target.value }))}
            />
          </div>
          <button
            type="submit"
            disabled={createInvoice.isPending}
            className="w-full rounded-xl bg-accent text-white py-3 text-body font-semibold active:opacity-80 disabled:opacity-50"
          >
            {createInvoice.isPending ? "Creating…" : "Create Invoice"}
          </button>
        </form>
      </div>
    </div>
  );
}

function NewBudgetLineModal({ onClose }: { onClose: () => void }) {
  const createBudgetLine = useCreateBudgetLine();
  const [form, setForm] = React.useState({
    project_id: "",
    category: "construction",
    description: "",
    budget_usd: "",
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.description || !form.budget_usd) return;
    await createBudgetLine.mutateAsync({
      project_id: form.project_id || undefined,
      category: form.category,
      description: form.description,
      budget_usd: parseFloat(form.budget_usd),
    } as never);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-bg-secondary rounded-t-2xl border-t border-separator/60 p-6 pb-safe">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-headline font-semibold text-label-primary">New Budget Line</h3>
          <button onClick={onClose} className="text-label-secondary active:opacity-60">
            <X className="h-5 w-5" />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-caption-1 text-label-secondary mb-1 block">Project</label>
            <input
              className="w-full rounded-xl bg-bg-elevated border border-separator/30 px-3 py-2 text-body text-label-primary"
              placeholder="Project name or ID"
              value={form.project_id}
              onChange={(e) => setForm(f => ({ ...f, project_id: e.target.value }))}
            />
          </div>
          <div>
            <label className="text-caption-1 text-label-secondary mb-1 block">Category *</label>
            <select
              required
              className="w-full rounded-xl bg-bg-elevated border border-separator/30 px-3 py-2 text-body text-label-primary"
              value={form.category}
              onChange={(e) => setForm(f => ({ ...f, category: e.target.value }))}
            >
              {BUDGET_CATEGORIES.map((c) => (
                <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-caption-1 text-label-secondary mb-1 block">Description *</label>
            <input
              required
              className="w-full rounded-xl bg-bg-elevated border border-separator/30 px-3 py-2 text-body text-label-primary"
              placeholder="Line item description"
              value={form.description}
              onChange={(e) => setForm(f => ({ ...f, description: e.target.value }))}
            />
          </div>
          <div>
            <label className="text-caption-1 text-label-secondary mb-1 block">Budget Amount (USD) *</label>
            <input
              type="number"
              step="0.01"
              required
              className="w-full rounded-xl bg-bg-elevated border border-separator/30 px-3 py-2 text-body text-label-primary"
              placeholder="0.00"
              value={form.budget_usd}
              onChange={(e) => setForm(f => ({ ...f, budget_usd: e.target.value }))}
            />
          </div>
          <button
            type="submit"
            disabled={createBudgetLine.isPending}
            className="w-full rounded-xl bg-accent text-white py-3 text-body font-semibold active:opacity-80 disabled:opacity-50"
          >
            {createBudgetLine.isPending ? "Creating…" : "Add Budget Line"}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── FAB dropdown ──────────────────────────────────────────────────────────────

function Fab({ onNewInvoice, onNewBudgetLine }: { onNewInvoice: () => void; onNewBudgetLine: () => void }) {
  const [open, setOpen] = React.useState(false);
  return (
    <div className="fixed bottom-[calc(env(safe-area-inset-bottom)+64px)] right-4 z-40 flex flex-col items-end gap-2">
      {open && (
        <>
          <button
            onClick={() => { setOpen(false); onNewBudgetLine(); }}
            className="flex items-center gap-2 rounded-2xl bg-bg-secondary border border-separator/30 px-4 py-2.5 text-body font-medium text-label-primary shadow-elevated active:opacity-70"
          >
            <FileText className="h-4 w-4 text-orange-400" />
            New Budget Line
          </button>
          <button
            onClick={() => { setOpen(false); onNewInvoice(); }}
            className="flex items-center gap-2 rounded-2xl bg-bg-secondary border border-separator/30 px-4 py-2.5 text-body font-medium text-label-primary shadow-elevated active:opacity-70"
          >
            <DollarSign className="h-4 w-4 text-accent" />
            New Invoice
          </button>
        </>
      )}
      <button
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex h-14 w-14 items-center justify-center rounded-full shadow-elevated",
          "bg-accent text-white active:opacity-80 transition-transform",
          open && "rotate-45",
        )}
        aria-label={open ? "Close menu" : "Add"}
      >
        <Plus className="h-6 w-6" strokeWidth={2.5} />
      </button>
    </div>
  );
}

// ── Invoice row (expandable) ──────────────────────────────────────────────────

function InvoiceRow({ invoice }: { invoice: Invoice }) {
  const [expanded, setExpanded] = React.useState(false);
  const updateInvoice = useUpdateInvoice(invoice.id);

  const markPaid = async () => {
    await updateInvoice.mutateAsync({
      status: "paid",
      paid_date: new Date().toISOString().split("T")[0] as never,
    } as never);
  };

  return (
    <div className="border-b border-separator/20 last:border-0">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left active:bg-bg-elevated"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span className="text-body font-medium text-label-primary truncate">
              {invoice.invoice_number ?? invoice.id.slice(0, 8)}
            </span>
            <InvoiceStatusBadge status={invoice.status} />
          </div>
          <div className="flex items-center gap-3 text-caption-1 text-label-secondary">
            <span>{fmtUSD(invoice.amount_usd)}</span>
            <span>Due {fmtDate(invoice.due_date)}</span>
          </div>
        </div>
        {expanded ? (
          <ChevronUp className="h-4 w-4 text-label-tertiary shrink-0" />
        ) : (
          <ChevronDown className="h-4 w-4 text-label-tertiary shrink-0" />
        )}
      </button>
      {expanded && (
        <div className="px-4 pb-3 space-y-2">
          <div className="text-caption-1 text-label-secondary space-y-1">
            {invoice.account_id && <div>Account: {invoice.account_id}</div>}
            <div>Issued: {fmtDate(invoice.issue_date)}</div>
            {invoice.paid_date && <div>Paid: {fmtDate(invoice.paid_date)}</div>}
            {invoice.notes && <div>Notes: {invoice.notes}</div>}
          </div>
          {invoice.status !== "paid" && invoice.status !== "cancelled" && (
            <button
              onClick={markPaid}
              disabled={updateInvoice.isPending}
              className="rounded-xl bg-green-400/10 text-green-400 px-4 py-2 text-callout font-medium active:opacity-70 disabled:opacity-50"
            >
              {updateInvoice.isPending ? "Updating…" : "Mark as Paid"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

type Tab = "overview" | "invoices";

export default function FinancePage() {
  const router = useRouter();
  const [tab, setTab] = React.useState<Tab>("overview");
  const [showNewInvoice, setShowNewInvoice] = React.useState(false);
  const [showNewBudgetLine, setShowNewBudgetLine] = React.useState(false);

  const { data: summary, isLoading: summaryLoading } = useFinanceSummary();
  const { data: arrData, isLoading: arrLoading } = useArrBreakdown();
  const { data: capexData, isLoading: capexLoading } = useCapexBreakdown();
  const { data: agingData, isLoading: agingLoading } = useArAging();
  const { data: invoiceData, isLoading: invoicesLoading } = useInvoices();

  return (
    <MobileShell>
      <TopBar
        title="Finance"
        right={
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-accent/10">
            <DollarSign className="h-4 w-4 text-accent" strokeWidth={1.75} />
          </span>
        }
      />

      {/* Tab toggle */}
      <div className="flex gap-1 mx-4 mt-3 p-1 bg-bg-secondary rounded-xl border border-separator/30">
        <button
          onClick={() => setTab("overview")}
          className={cn(
            "flex-1 py-2 rounded-lg text-callout font-medium transition-colors",
            tab === "overview"
              ? "bg-accent text-white"
              : "text-label-secondary active:text-label-primary",
          )}
        >
          Overview
        </button>
        <button
          onClick={() => setTab("invoices")}
          className={cn(
            "flex-1 py-2 rounded-lg text-callout font-medium transition-colors",
            tab === "invoices"
              ? "bg-accent text-white"
              : "text-label-secondary active:text-label-primary",
          )}
        >
          Invoices
          {(summary?.overdue_invoices_count ?? 0) > 0 && (
            <span className="ml-1.5 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-400 px-1 text-[10px] font-semibold text-white">
              {summary!.overdue_invoices_count}
            </span>
          )}
        </button>
      </div>

      {tab === "overview" && (
        <div className="pb-8">
          {/* Section 1 — Portfolio Summary */}
          <SectionHeader title="Portfolio Summary" />
          {summaryLoading ? (
            <div className="px-4">
              <div className="grid grid-cols-2 gap-3">
                {[0, 1, 2, 3].map((i) => (
                  <div key={i} className="rounded-2xl bg-bg-secondary border border-separator/30 h-24 animate-pulse" />
                ))}
              </div>
            </div>
          ) : summary ? (
            <div className="px-4 grid grid-cols-2 gap-3">
              <StatCard
                label="Total ARR"
                value={fmtUSD(summary.total_arr_usd)}
                sub="Won deals"
                color="green"
                icon={TrendingUp}
              />
              <StatCard
                label="Pipeline Value"
                value={fmtUSD(summary.total_pipeline_value_usd)}
                sub="Active deals"
                color="blue"
                icon={DollarSign}
              />
              <StatCard
                label="CapEx Committed"
                value={fmtUSD(summary.total_capex_committed_usd)}
                sub="Equipment"
                color="orange"
                icon={TrendingDown}
              />
              <StatCard
                label="Equipment Capex"
                value={fmtUSD(summary.capex_equipment_usd)}
                sub="Ordered equipment"
                color="orange"
                icon={TrendingDown}
              />
              <StatCard
                label="Outstanding"
                value={fmtUSD(summary.total_outstanding_invoices_usd)}
                sub={
                  summary.overdue_invoices_count > 0
                    ? `${summary.overdue_invoices_count} overdue`
                    : "No overdue"
                }
                color={summary.overdue_invoices_count > 0 ? "red" : "green"}
                icon={AlertCircle}
              />
            </div>
          ) : null}

          {/* Section 2 — ARR */}
          <SectionHeader title="Revenue (ARR)" count={arrData?.total ?? 0} />
          {arrLoading ? (
            <div className="px-4 space-y-2">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-16 rounded-2xl bg-bg-secondary animate-pulse" />
              ))}
            </div>
          ) : arrData?.items.length === 0 ? (
            <div className="px-4 py-8 text-center text-label-tertiary text-callout">
              No won deals yet
            </div>
          ) : (
            <div className="mx-4 rounded-2xl bg-bg-secondary border border-separator/30 divide-y divide-separator/20 overflow-hidden">
              {arrData?.items.map((line) => (
                <button
                  key={line.deal_id}
                  type="button"
                  onClick={() => router.push(`/pipeline/deals/${line.deal_id}`)}
                  className="w-full flex items-center gap-3 px-4 py-3 text-left active:bg-bg-elevated"
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-body font-medium text-label-primary truncate">
                      {line.account_name}
                    </div>
                    <div className="text-caption-1 text-label-secondary">
                      {line.deal_name}
                      {line.mw_required != null && ` · ${line.mw_required} MW`}
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-body font-semibold text-green-400">
                      {fmtUSD(line.value_usd)}
                    </div>
                    <div className="text-caption-1 text-label-tertiary">/ yr</div>
                  </div>
                  <ChevronRight className="h-4 w-4 text-label-tertiary shrink-0" />
                </button>
              ))}
            </div>
          )}

          {/* Section 3 — CapEx by Project */}
          <SectionHeader title="CapEx by Project" count={capexData?.total ?? 0} />
          {capexLoading ? (
            <div className="px-4 space-y-2">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-20 rounded-2xl bg-bg-secondary animate-pulse" />
              ))}
            </div>
          ) : capexData?.items.length === 0 ? (
            <div className="px-4 py-8 text-center text-label-tertiary text-callout">
              No projects yet
            </div>
          ) : (
            <div className="mx-4 rounded-2xl bg-bg-secondary border border-separator/30 divide-y divide-separator/20 overflow-hidden">
              {capexData?.items.map((proj) => {
                const overBudget = (proj.forecast_usd ?? 0) > (proj.budget_usd ?? 0);
                const variance = (proj.forecast_usd ?? 0) - (proj.budget_usd ?? 0);
                return (
                  <button
                    key={proj.project_id}
                    type="button"
                    onClick={() => router.push(`/projects/${proj.project_id}`)}
                    className="w-full px-4 py-3 text-left active:bg-bg-elevated"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-body font-medium text-label-primary truncate">
                        {proj.project_name}
                      </span>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <span className={cn(
                          "text-caption-1 font-medium",
                          overBudget ? "text-red-400" : "text-green-400",
                        )}>
                          {overBudget ? "+" : ""}{fmtUSD(variance)}
                        </span>
                        <ChevronRight className="h-4 w-4 text-label-tertiary" />
                      </div>
                    </div>
                    <div className="flex gap-4 text-caption-1 text-label-secondary">
                      <span>Budget: {fmtUSD(proj.budget_usd)}</span>
                      <span>Forecast: {fmtUSD(proj.forecast_usd)}</span>
                    </div>
                    <CapexBar budget={proj.budget_usd} forecast={proj.forecast_usd} />
                  </button>
                );
              })}
            </div>
          )}

          {/* Section 4 — AR Aging */}
          <SectionHeader title="AR Aging" />
          {agingLoading ? (
            <div className="mx-4 h-32 rounded-2xl bg-bg-secondary animate-pulse" />
          ) : agingData ? (
            <div className="mx-4 rounded-2xl bg-bg-secondary border border-separator/30 overflow-hidden">
              <div className="divide-y divide-separator/20">
                {agingData.buckets.map((bucket, i) => {
                  const isRed = i >= 4 && bucket.count > 0;
                  return (
                    <div key={bucket.label} className="flex items-center px-4 py-3">
                      <div className="flex-1">
                        <span className={cn(
                          "text-body font-medium",
                          isRed ? "text-red-400" : "text-label-primary",
                        )}>
                          {bucket.label}
                        </span>
                      </div>
                      <div className="text-right">
                        <div className={cn(
                          "text-body font-semibold",
                          isRed ? "text-red-400" : "text-label-primary",
                        )}>
                          {fmtUSD(bucket.total_usd)}
                        </div>
                        <div className="text-caption-1 text-label-tertiary">
                          {bucket.count} invoice{bucket.count !== 1 ? "s" : ""}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="border-t border-separator/40 px-4 py-3 flex items-center justify-between bg-bg-elevated/30">
                <span className="text-callout font-semibold text-label-primary">Total Outstanding</span>
                <span className="text-callout font-semibold text-label-primary">
                  {fmtUSD(agingData.total_outstanding_usd)}
                </span>
              </div>
            </div>
          ) : (
            <div className="px-4 py-8 text-center text-label-tertiary text-callout">
              No outstanding invoices
            </div>
          )}
        </div>
      )}

      {tab === "invoices" && (
        <div className="pb-8">
          <SectionHeader title="All Invoices" count={invoiceData?.total ?? 0} />
          {invoicesLoading ? (
            <div className="mx-4 space-y-2">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="h-16 rounded-2xl bg-bg-secondary animate-pulse" />
              ))}
            </div>
          ) : !invoiceData?.items.length ? (
            <div className="px-4 py-16 text-center">
              <DollarSign className="mx-auto h-10 w-10 text-label-quaternary mb-3" strokeWidth={1} />
              <p className="text-body text-label-secondary">No invoices yet</p>
              <p className="text-callout text-label-tertiary mt-1">
                Tap + to create your first invoice
              </p>
            </div>
          ) : (
            <div className="mx-4 rounded-2xl bg-bg-secondary border border-separator/30 overflow-hidden">
              {invoiceData.items.map((inv) => (
                <InvoiceRow key={inv.id} invoice={inv} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* FAB */}
      <Fab
        onNewInvoice={() => setShowNewInvoice(true)}
        onNewBudgetLine={() => setShowNewBudgetLine(true)}
      />

      {/* Modals */}
      {showNewInvoice && <NewInvoiceModal onClose={() => setShowNewInvoice(false)} />}
      {showNewBudgetLine && <NewBudgetLineModal onClose={() => setShowNewBudgetLine(false)} />}
    </MobileShell>
  );
}
