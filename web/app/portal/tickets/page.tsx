"use client";

/**
 * /portal/tickets — Full Ticket List (Sprint 4B)
 *
 * All customer tickets, status filter, "New Ticket" modal.
 * Each ticket card expandable → shows description + comment box.
 */

import * as React from "react";
import { Plus, ChevronDown, ChevronUp, X, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  usePortalTickets,
  useCreatePortalTicket,
  usePatchPortalTicket,
} from "@/lib/api";
import type { PortalTicket } from "@/lib/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

const STATUS_FILTERS = [
  { value: "", label: "All" },
  { value: "open", label: "Open" },
  { value: "in_progress", label: "In Progress" },
  { value: "resolved", label: "Resolved" },
] as const;

function severityBadge(s: string) {
  const map: Record<string, string> = {
    P1: "bg-red-100 text-red-700 border border-red-200",
    P2: "bg-orange-100 text-orange-700 border border-orange-200",
    P3: "bg-yellow-100 text-yellow-700 border border-yellow-200",
    P4: "bg-gray-100 text-gray-600 border border-gray-200",
  };
  return map[s] ?? "bg-gray-100 text-gray-600 border border-gray-200";
}

function statusBadge(s: string) {
  const map: Record<string, string> = {
    open: "bg-red-50 text-red-600 border-red-200",
    in_progress: "bg-yellow-50 text-yellow-700 border-yellow-200",
    resolved: "bg-green-50 text-green-700 border-green-200",
    closed: "bg-gray-50 text-gray-500 border-gray-200",
  };
  return map[s] ?? "bg-gray-50 text-gray-500 border-gray-200";
}

function statusLabel(s: string) {
  return (
    { open: "Open", in_progress: "In Progress", resolved: "Resolved", closed: "Closed" }[s] ?? s
  );
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

// ── Ticket Card ───────────────────────────────────────────────────────────────

function TicketCard({ ticket }: { ticket: PortalTicket }) {
  const [expanded, setExpanded] = React.useState(false);
  const [comment, setComment] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const patch = usePatchPortalTicket(ticket.id);

  async function handleComment(e: React.FormEvent) {
    e.preventDefault();
    if (!comment.trim()) return;
    setSubmitting(true);
    try {
      await patch.mutateAsync({ comment: comment.trim() });
      setComment("");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      {/* Header row */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left px-5 py-4 flex items-start gap-3 hover:bg-gray-50 transition-colors"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1.5">
            <span
              className={cn(
                "text-xs font-bold rounded-full px-2 py-0.5",
                severityBadge(ticket.severity),
              )}
            >
              {ticket.severity}
            </span>
            <span
              className={cn(
                "text-xs rounded-full px-2 py-0.5 border",
                statusBadge(ticket.status),
              )}
            >
              {statusLabel(ticket.status)}
            </span>
          </div>
          <p className="text-sm font-medium text-gray-900 line-clamp-2">{ticket.title}</p>
          <p className="text-xs text-gray-400 mt-1">{fmtDate(ticket.created_at)}</p>
        </div>
        <div className="shrink-0 mt-0.5 text-gray-400">
          {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </div>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="border-t border-gray-100 px-5 py-4 space-y-4">
          {ticket.description ? (
            <div>
              <p className="text-xs font-medium text-gray-500 mb-1.5">Description</p>
              <p className="text-sm text-gray-700 whitespace-pre-wrap">{ticket.description}</p>
            </div>
          ) : (
            <p className="text-sm text-gray-400 italic">No description provided.</p>
          )}

          {ticket.resolution_notes && (
            <div>
              <p className="text-xs font-medium text-gray-500 mb-1.5">Comments &amp; Updates</p>
              <p className="text-sm text-gray-700 whitespace-pre-wrap bg-gray-50 rounded-lg px-3 py-2">
                {ticket.resolution_notes}
              </p>
            </div>
          )}

          {/* Comment box — only for open/in-progress tickets */}
          {ticket.status !== "resolved" && ticket.status !== "closed" && (
            <form onSubmit={handleComment} className="space-y-2">
              <label className="block text-xs font-medium text-gray-500">
                Add a comment
              </label>
              <textarea
                rows={2}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Add additional details or a follow-up…"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              />
              <button
                type="submit"
                disabled={!comment.trim() || submitting}
                className="text-xs font-semibold bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded-lg px-3 py-1.5 transition-colors flex items-center gap-1.5"
              >
                {submitting && <Loader2 className="w-3 h-3 animate-spin" />}
                Post Comment
              </button>
            </form>
          )}
        </div>
      )}
    </div>
  );
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
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">New Ticket</h2>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>
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
              rows={4}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Provide details about the issue, steps to reproduce, impact, etc."
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

export default function PortalTicketsPage() {
  const [statusFilter, setStatusFilter] = React.useState<string>("");
  const [newTicketOpen, setNewTicketOpen] = React.useState(false);

  const { data, isLoading } = usePortalTickets(statusFilter || undefined);
  const tickets = data?.items ?? [];

  return (
    <div className="space-y-5">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Support Tickets</h1>
        <button
          type="button"
          onClick={() => setNewTicketOpen(true)}
          className="flex items-center gap-1.5 text-sm font-semibold bg-blue-600 hover:bg-blue-700 text-white rounded-lg px-4 py-2 transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Ticket
        </button>
      </div>

      {/* Status filter pills */}
      <div className="flex gap-2 flex-wrap">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            onClick={() => setStatusFilter(f.value)}
            className={cn(
              "text-sm rounded-full px-3 py-1.5 font-medium border transition-colors",
              statusFilter === f.value
                ? "bg-blue-600 text-white border-blue-600"
                : "bg-white text-gray-600 border-gray-200 hover:border-blue-400 hover:text-blue-600",
            )}
          >
            {f.label}
          </button>
        ))}
        <span className="ml-auto text-sm text-gray-400 self-center">
          {data?.total ?? 0} ticket{data?.total !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Ticket list */}
      {isLoading ? (
        <div className="flex items-center justify-center py-16 text-gray-400 text-sm">
          <Loader2 className="w-5 h-5 animate-spin mr-2" />
          Loading tickets…
        </div>
      ) : tickets.length === 0 ? (
        <div className="bg-white rounded-2xl border border-gray-200 px-5 py-12 text-center">
          <p className="text-gray-500 text-sm">
            {statusFilter ? `No ${statusFilter.replace("_", " ")} tickets.` : "No tickets yet."}
          </p>
          <button
            type="button"
            onClick={() => setNewTicketOpen(true)}
            className="mt-3 text-blue-600 text-sm font-medium hover:text-blue-700"
          >
            Submit your first ticket →
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {tickets.map((t) => (
            <TicketCard key={t.id} ticket={t} />
          ))}
        </div>
      )}

      {newTicketOpen && <NewTicketModal onClose={() => setNewTicketOpen(false)} />}
    </div>
  );
}
