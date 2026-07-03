"use client";

/**
 * /portal/invoices — Invoice List (Sprint 4B)
 *
 * Read-only list with status filter: All | Unpaid | Paid | Overdue
 */

import * as React from "react";
import { Loader2, FileText } from "lucide-react";
import { cn } from "@/lib/utils";
import { usePortalInvoices } from "@/lib/api";
import type { PortalInvoice } from "@/lib/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

const STATUS_FILTERS = [
  { value: "all", label: "All" },
  { value: "unpaid", label: "Unpaid" },
  { value: "paid", label: "Paid" },
  { value: "overdue", label: "Overdue" },
] as const;

type FilterValue = (typeof STATUS_FILTERS)[number]["value"];

function statusBadge(s: string) {
  const map: Record<string, string> = {
    paid: "bg-green-50 text-green-700 border-green-200",
    sent: "bg-blue-50 text-blue-700 border-blue-200",
    overdue: "bg-red-50 text-red-600 border-red-200",
    draft: "bg-gray-50 text-gray-500 border-gray-200",
    cancelled: "bg-gray-50 text-gray-400 border-gray-200",
  };
  return map[s] ?? "bg-gray-50 text-gray-500 border-gray-200";
}

function statusLabel(s: string) {
  const map: Record<string, string> = {
    sent: "Unpaid",
    paid: "Paid",
    overdue: "Overdue",
    draft: "Draft",
    cancelled: "Cancelled",
  };
  return map[s] ?? s;
}

function fmtDate(d: string) {
  return new Date(d).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function fmtCurrency(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

// ── Invoice Row ───────────────────────────────────────────────────────────────

function InvoiceRow({ invoice }: { invoice: PortalInvoice }) {
  const isOverdue = invoice.status === "overdue";
  const displayNumber =
    invoice.invoice_number ?? `INV-${invoice.id.slice(0, 8).toUpperCase()}`;

  return (
    <div
      className={cn(
        "flex items-center gap-4 px-5 py-4 hover:bg-gray-50 transition-colors",
        isOverdue && "bg-red-50/40",
      )}
    >
      {/* Icon */}
      <div className="shrink-0 w-9 h-9 rounded-lg bg-gray-100 flex items-center justify-center">
        <FileText className="w-4 h-4 text-gray-500" />
      </div>

      {/* Number + dates */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-gray-900">{displayNumber}</p>
        <p className="text-xs text-gray-400 mt-0.5">
          Issued {fmtDate(invoice.issue_date)} · Due {fmtDate(invoice.due_date)}
          {invoice.paid_date && ` · Paid ${fmtDate(invoice.paid_date)}`}
        </p>
      </div>

      {/* Amount */}
      <div className="shrink-0 text-right">
        <p className="text-sm font-bold text-gray-900">{fmtCurrency(invoice.amount_usd)}</p>
      </div>

      {/* Status badge */}
      <div className="shrink-0">
        <span
          className={cn(
            "text-xs font-semibold rounded-full px-2.5 py-1 border",
            statusBadge(invoice.status),
          )}
        >
          {statusLabel(invoice.status)}
        </span>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PortalInvoicesPage() {
  const [filter, setFilter] = React.useState<FilterValue>("all");

  const { data, isLoading } = usePortalInvoices(filter !== "all" ? filter : undefined);
  const invoices = data?.items ?? [];

  // Totals for the current filter
  const total = data?.total ?? 0;
  const totalAmount = invoices.reduce((sum, inv) => sum + inv.amount_usd, 0);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold text-gray-900">Invoices</h1>
        {total > 0 && (
          <div className="text-sm text-gray-500">
            {total} invoice{total !== 1 ? "s" : ""} ·{" "}
            <span className="font-semibold text-gray-700">{fmtCurrency(totalAmount)}</span>
          </div>
        )}
      </div>

      {/* Filter pills */}
      <div className="flex gap-2 flex-wrap">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            onClick={() => setFilter(f.value)}
            className={cn(
              "text-sm rounded-full px-3 py-1.5 font-medium border transition-colors",
              filter === f.value
                ? "bg-blue-600 text-white border-blue-600"
                : "bg-white text-gray-600 border-gray-200 hover:border-blue-400 hover:text-blue-600",
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Table card */}
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
        {/* Column headers */}
        <div className="hidden sm:flex items-center gap-4 px-5 py-3 border-b border-gray-100 bg-gray-50/80 text-xs font-semibold text-gray-500 uppercase tracking-wide">
          <div className="w-9 shrink-0" />
          <div className="flex-1">Invoice</div>
          <div className="shrink-0 text-right w-28">Amount</div>
          <div className="shrink-0 w-20 text-center">Status</div>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-16 text-gray-400 text-sm">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />
            Loading invoices…
          </div>
        ) : invoices.length === 0 ? (
          <div className="px-5 py-12 text-center">
            <FileText className="w-8 h-8 mx-auto mb-2 text-gray-200" />
            <p className="text-gray-500 text-sm">
              {filter !== "all"
                ? `No ${filter} invoices.`
                : "No invoices yet."}
            </p>
          </div>
        ) : (
          <div className="divide-y divide-gray-50">
            {invoices.map((inv) => (
              <InvoiceRow key={inv.id} invoice={inv} />
            ))}
          </div>
        )}
      </div>

      <p className="text-xs text-gray-400 text-center">
        Invoice records are read-only. Contact your account manager for billing questions.
      </p>
    </div>
  );
}
