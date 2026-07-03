"use client";

/**
 * /portal/dashboard — Main Customer Dashboard (Sprint 4B)
 *
 * Header: "Welcome back, [Account Name]" + campus name badge
 * Status Card: campus uptime last 30 days
 * 2-column: Recent Tickets | Recent Invoices
 */

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Ticket,
  FileText,
  AlertTriangle,
  CheckCircle,
  Clock,
  ChevronRight,
  Plus,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  usePortalMe,
  usePortalUptime,
  usePortalTickets,
  usePortalInvoices,
  useCreatePortalTicket,
} from "@/lib/api";
import type { PortalTicket, PortalInvoice } from "@/lib/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

function uptimeColor(pct: number | null | undefined): string {
  if (pct == null) return "text-gray-400";
  if (pct >= 99) return "text-green-600";
  if (pct >= 95) return "text-yellow-500";
  return "text-red-500";
}

function uptimeBg(pct: number | null | undefined): string {
  if (pct == null) return "bg-gray-100";
  if (pct >= 99) return "bg-green-50 border-green-200";
  if (pct >= 95) return "bg-yellow-50 border-yellow-200";
  return "bg-red-50 border-red-200";
}

function severityBadge(s: string) {
  const map: Record<string, string> = {
    P1: "bg-red-100 text-red-700",
    P2: "bg-orange-100 text-orange-700",
    P3: "bg-yellow-100 text-yellow-700",
    P4: "bg-gray-100 text-gray-600",
  };
  return map[s] ?? "bg-gray-100 text-gray-600";
}

function ticketStatusBadge(s: string) {
  const map: Record<string, string> = {
    open: "bg-red-50 text-red-600",
    in_progress: "bg-yellow-50 text-yellow-700",
    resolved: "bg-green-50 text-green-700",
    closed: "bg-gray-100 text-gray-500",
  };
  return map[s] ?? "bg-gray-100 text-gray-500";
}

function invoiceStatusBadge(s: string) {
  const map: Record<string, string> = {
    paid: "bg-green-50 text-green-700",
    sent: "bg-blue-50 text-blue-700",
    overdue: "bg-red-50 text-red-600",
    draft: "bg-gray-100 text-gray-500",
    cancelled: "bg-gray-100 text-gray-400",
  };
  return map[s] ?? "bg-gray-100 text-gray-500";
}

function invoiceStatusLabel(s: string) {
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

function fmtDateTime(iso: string) {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

// ── New Ticket Modal ──────────────────────────────────────────────────────────

function NewTicketModal({ onClose }: { onClose: () => void }) {
  const [title, setTitle] = React.useState("");
  const [severity, setSeverity] = React.useState("P3");
  const [description, setDescription] = React.useState("");
  const createTicket = useCreatePortalTicket();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    try {
      await createTicket.mutateAsync({ title, severity, description: description || undefined });
      onClose();
    } catch (_) {}
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md mx-4 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Submit a Ticket</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Title</label>
            <input
              type="text"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Brief description of the issue"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Severity</label>
            <select
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="P1">P1 — Critical</option>
              <option value="P2">P2 — High</option>
              <option value="P3">P3 — Medium</option>
              <option value="P4">P4 — Low</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
            <textarea
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional details about the issue…"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
            />
          </div>
          <div className="flex gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 rounded-lg border border-gray-300 text-gray-700 py-2 text-sm font-medium hover:bg-gray-50 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!title.trim() || createTicket.isPending}
              className="flex-1 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white py-2 text-sm font-medium transition-colors"
            >
              {createTicket.isPending ? "Submitting…" : "Submit Ticket"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PortalDashboard() {
  const [newTicketOpen, setNewTicketOpen] = React.useState(false);

  const { data: me, isLoading: meLoading } = usePortalMe();
  const { data: uptime } = usePortalUptime();
  const { data: ticketsData } = usePortalTickets("open");
  const { data: invoicesData } = usePortalInvoices();

  const recentTickets: PortalTicket[] = (ticketsData?.items ?? []).slice(0, 3);
  const recentInvoices: PortalInvoice[] = (invoicesData?.items ?? []).slice(0, 3);

  if (meLoading) {
    return (
      <div className="flex items-center justify-center py-24 text-gray-400 text-sm">
        Loading…
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-2xl font-bold text-gray-900">
          Welcome back, {me?.name ?? "…"}
        </h1>
        {me?.linked_campus_name && (
          <span className="inline-flex items-center gap-1 text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200 rounded-full px-2.5 py-1">
            {me.linked_campus_name}
          </span>
        )}
      </div>

      {/* Uptime Card */}
      <div
        className={cn(
          "rounded-2xl border p-6 flex flex-col sm:flex-row sm:items-center gap-4",
          uptimeBg(uptime?.uptime_pct),
        )}
      >
        {uptime?.message === "Campus assignment pending" || !me?.linked_campus_id ? (
          <div className="text-gray-500 text-sm">
            <AlertTriangle className="w-5 h-5 inline mr-2 text-yellow-500" />
            Campus assignment pending — contact your account manager.
          </div>
        ) : (
          <>
            <div className="flex-1">
              <p className="text-sm text-gray-500 mb-1">
                Campus Uptime — Last 30 Days
              </p>
              <p className="text-sm font-medium text-gray-700">
                {uptime?.campus_name ?? "—"}
              </p>
            </div>
            <div className={cn("text-5xl font-extrabold tabular-nums", uptimeColor(uptime?.uptime_pct))}>
              {uptime?.uptime_pct != null ? `${uptime.uptime_pct.toFixed(2)}%` : "—"}
            </div>
          </>
        )}
      </div>

      {/* 2-column grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Recent Tickets */}
        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-800 flex items-center gap-2">
              <Ticket className="w-4 h-4 text-blue-500" />
              Recent Open Tickets
            </h2>
            <Link
              href="/portal/tickets"
              className="text-xs text-blue-600 hover:text-blue-700 flex items-center gap-0.5"
            >
              View all <ChevronRight className="w-3.5 h-3.5" />
            </Link>
          </div>
          <div className="divide-y divide-gray-50">
            {recentTickets.length === 0 ? (
              <div className="px-5 py-6 text-sm text-gray-400 text-center">
                <CheckCircle className="w-5 h-5 mx-auto mb-2 text-green-400" />
                No open tickets
              </div>
            ) : (
              recentTickets.map((t) => (
                <div key={t.id} className="px-5 py-3.5">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm text-gray-800 font-medium line-clamp-1">{t.title}</p>
                    <span
                      className={cn(
                        "shrink-0 text-xs font-semibold rounded-full px-2 py-0.5",
                        severityBadge(t.severity),
                      )}
                    >
                      {t.severity}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 mt-1">
                    <span
                      className={cn(
                        "text-xs rounded-full px-2 py-0.5",
                        ticketStatusBadge(t.status),
                      )}
                    >
                      {t.status.replace("_", " ")}
                    </span>
                    <span className="text-xs text-gray-400">
                      {fmtDateTime(t.created_at)}
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
          <div className="px-5 py-3 border-t border-gray-100">
            <button
              type="button"
              onClick={() => setNewTicketOpen(true)}
              className="flex items-center gap-1.5 text-xs font-semibold text-blue-600 hover:text-blue-700 transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              Submit a ticket
            </button>
          </div>
        </div>

        {/* Recent Invoices */}
        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-800 flex items-center gap-2">
              <FileText className="w-4 h-4 text-blue-500" />
              Recent Invoices
            </h2>
            <Link
              href="/portal/invoices"
              className="text-xs text-blue-600 hover:text-blue-700 flex items-center gap-0.5"
            >
              View all <ChevronRight className="w-3.5 h-3.5" />
            </Link>
          </div>
          <div className="divide-y divide-gray-50">
            {recentInvoices.length === 0 ? (
              <div className="px-5 py-6 text-sm text-gray-400 text-center">
                <FileText className="w-5 h-5 mx-auto mb-2 text-gray-300" />
                No invoices yet
              </div>
            ) : (
              recentInvoices.map((inv) => (
                <div key={inv.id} className="px-5 py-3.5">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm text-gray-800 font-medium">
                      {inv.invoice_number ?? `INV-${inv.id.slice(0, 8).toUpperCase()}`}
                    </p>
                    <span
                      className={cn(
                        "shrink-0 text-xs font-semibold rounded-full px-2 py-0.5",
                        invoiceStatusBadge(inv.status),
                      )}
                    >
                      {invoiceStatusLabel(inv.status)}
                    </span>
                  </div>
                  <div className="flex items-center justify-between mt-1">
                    <span className="text-sm font-semibold text-gray-900">
                      {fmtCurrency(inv.amount_usd)}
                    </span>
                    <span className="text-xs text-gray-400">
                      Due {fmtDate(inv.due_date)}
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {newTicketOpen && <NewTicketModal onClose={() => setNewTicketOpen(false)} />}
    </div>
  );
}
