"use client";

/**
 * /customers/[id] — Customer Detail Page (Sprint 2A)
 *
 * Tabs: Tickets | Notes | Details
 * Design: dark Quill theme, iOS-style cards, accent blue #0A84FF.
 */

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  Ticket,
  StickyNote,
  Settings2,
  Plus,
  X,
  ChevronDown,
  ChevronRight,
  Users,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { ErrorBanner } from "@/components/ui/error-banner";
import {
  useCustomer,
  useCustomerTickets,
  useCreateTicket,
  useUpdateTicket,
  useCustomerNotes,
  useAddNote,
  useUpdateCustomer,
  useCampuses,
} from "@/lib/api";
import type { CustomerDetail, SupportTicket, AccountNote } from "@/lib/schemas";

// ── Helpers ───────────────────────────────────────────────────────────────────

function healthColor(score: number | null | undefined): string {
  if (score == null) return "text-label-secondary";
  if (score >= 80) return "text-green-400";
  if (score >= 60) return "text-yellow-400";
  return "text-red-400";
}

function severityBadge(severity: string): string {
  switch (severity) {
    case "P1": return "bg-red-500 text-white";
    case "P2": return "bg-orange-500 text-white";
    case "P3": return "bg-yellow-500 text-black";
    case "P4": return "bg-zinc-500 text-white";
    default:   return "bg-zinc-600 text-white";
  }
}

function statusBadge(s: string): string {
  switch (s) {
    case "open":        return "text-red-400 bg-red-400/10";
    case "in_progress": return "text-yellow-400 bg-yellow-400/10";
    case "resolved":    return "text-green-400 bg-green-400/10";
    case "closed":      return "text-label-tertiary bg-bg-elevated";
    default:            return "text-label-secondary bg-bg-elevated";
  }
}

function statusLabel(s: string): string {
  return ({ open: "Open", in_progress: "In Progress", resolved: "Resolved", closed: "Closed" }[s] ?? s);
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function fmtDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

// ── Tabs ──────────────────────────────────────────────────────────────────────

const TABS = [
  { key: "tickets", label: "Tickets", icon: Ticket },
  { key: "notes", label: "Notes", icon: StickyNote },
  { key: "details", label: "Details", icon: Settings2 },
] as const;

type TabKey = typeof TABS[number]["key"];

// ── Tickets Tab ───────────────────────────────────────────────────────────────

const STATUS_ORDER = ["open", "in_progress", "resolved", "closed"] as const;

function TicketsTab({ accountId }: { accountId: string }) {
  const [newTicketOpen, setNewTicketOpen] = React.useState(false);
  const [expanded, setExpanded] = React.useState<string | null>(null);
  const [newTitle, setNewTitle] = React.useState("");
  const [newSeverity, setNewSeverity] = React.useState("P3");
  const [newDesc, setNewDesc] = React.useState("");

  const { data, isLoading, error } = useCustomerTickets(accountId);
  const createTicket = useCreateTicket(accountId);

  const [resolutionDrafts, setResolutionDrafts] = React.useState<Record<string, string>>({});

  // Per-ticket update mutation — call hooks at component level for a fixed set of tickets
  // We use a single PATCH mutation routed via ticketId state
  const [patchingTicket, setPatchingTicket] = React.useState<string | null>(null);
  const updateTicketMutation = useUpdateTicket(accountId, patchingTicket ?? "__none__");

  async function handlePatch(ticketId: string, body: Record<string, unknown>) {
    setPatchingTicket(ticketId);
    // Wait for state to propagate — use the mutation directly after setting patchingTicket
    await new Promise<void>((res) => setTimeout(res, 0));
    try {
      await updateTicketMutation.mutateAsync(body as Parameters<typeof updateTicketMutation.mutateAsync>[0]);
    } finally {
      setPatchingTicket(null);
    }
  }

  async function handleCreate() {
    if (!newTitle.trim()) return;
    try {
      await createTicket.mutateAsync({ title: newTitle, severity: newSeverity, description: newDesc || undefined });
      setNewTitle("");
      setNewSeverity("P3");
      setNewDesc("");
      setNewTicketOpen(false);
    } catch (_) {}
  }

  const tickets = data?.items ?? [];

  return (
    <div className="pt-4">
      {/* New ticket button */}
      <div className="flex justify-end mb-4">
        <button
          type="button"
          onClick={() => setNewTicketOpen(true)}
          className="flex items-center gap-1.5 text-caption-1 font-semibold text-accent bg-accent/10 rounded-full px-3 py-1.5 active:scale-95"
        >
          <Plus className="w-3.5 h-3.5" />
          New Ticket
        </button>
      </div>

      {/* New ticket modal */}
      {newTicketOpen && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-md bg-bg-primary rounded-t-3xl p-6 pb-safe-bottom shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-headline font-semibold text-label-primary">New Ticket</h3>
              <button type="button" onClick={() => setNewTicketOpen(false)}>
                <X className="w-5 h-5 text-label-secondary" />
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-caption-1 text-label-secondary">Title</label>
                <input
                  className="mt-1 w-full rounded-xl bg-chrome/80 border border-separator/40 px-3 py-2 text-body text-label-primary placeholder:text-label-quaternary focus:outline-none focus:border-accent/60"
                  placeholder="Describe the issue…"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                />
              </div>
              <div>
                <label className="text-caption-1 text-label-secondary">Severity</label>
                <select
                  className="mt-1 w-full rounded-xl bg-chrome/80 border border-separator/40 px-3 py-2 text-body text-label-primary focus:outline-none"
                  value={newSeverity}
                  onChange={(e) => setNewSeverity(e.target.value)}
                >
                  {["P1", "P2", "P3", "P4"].map((s) => (
                    <option key={s} value={s}>{s} {s === "P1" ? "— Critical" : s === "P2" ? "— High" : s === "P3" ? "— Medium" : "— Low"}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-caption-1 text-label-secondary">Description (optional)</label>
                <textarea
                  className="mt-1 w-full rounded-xl bg-chrome/80 border border-separator/40 px-3 py-2 text-body text-label-primary placeholder:text-label-quaternary focus:outline-none h-20 resize-none"
                  placeholder="Additional context…"
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                />
              </div>
              <button
                type="button"
                onClick={handleCreate}
                disabled={!newTitle.trim() || createTicket.isPending}
                className="w-full rounded-xl bg-accent text-white font-semibold py-3 active:scale-98 disabled:opacity-50"
              >
                {createTicket.isPending ? "Creating…" : "Create Ticket"}
              </button>
              {createTicket.isError && (
                <p className="text-caption-1 text-red-400">{createTicket.error?.message}</p>
              )}
            </div>
          </div>
        </div>
      )}

      {error && <ErrorBanner message={error.message} />}
      {isLoading && (
        <div className="space-y-2">
          {[1, 2].map((i) => (
            <div key={i} className="h-20 rounded-2xl bg-chrome/60 animate-pulse" />
          ))}
        </div>
      )}

      {!isLoading && tickets.length === 0 && (
        <p className="text-body text-label-tertiary text-center py-10">No tickets yet.</p>
      )}

      {tickets.map((ticket) => {
        const isExpanded = expanded === ticket.id;
        return (
          <div
            key={ticket.id}
            className="rounded-2xl bg-chrome/80 border border-separator/40 mb-3 overflow-hidden"
          >
            {/* Ticket header row */}
            <button
              type="button"
              onClick={() => setExpanded(isExpanded ? null : ticket.id)}
              className="w-full text-left px-4 py-3 flex items-start gap-3"
            >
              <span className={cn("text-caption-2 font-bold rounded px-1.5 py-0.5 mt-0.5 flex-shrink-0", severityBadge(ticket.severity))}>
                {ticket.severity}
              </span>
              <div className="flex-1 min-w-0">
                <p className="text-body font-medium text-label-primary truncate">{ticket.title}</p>
                <div className="flex items-center gap-2 mt-1">
                  <span className={cn("text-caption-2 font-semibold rounded-full px-1.5 py-0.5", statusBadge(ticket.status))}>
                    {statusLabel(ticket.status)}
                  </span>
                  <span className="text-caption-2 text-label-quaternary">{fmtDate(ticket.created_at)}</span>
                  {ticket.resolved_at && (
                    <span className="text-caption-2 text-green-400">Resolved {fmtDate(ticket.resolved_at)}</span>
                  )}
                </div>
              </div>
              {isExpanded ? (
                <ChevronDown className="w-4 h-4 text-label-quaternary flex-shrink-0 mt-1" />
              ) : (
                <ChevronRight className="w-4 h-4 text-label-quaternary flex-shrink-0 mt-1" />
              )}
            </button>

            {/* Expanded ticket body */}
            {isExpanded && (
              <div className="px-4 pb-4 border-t border-separator/30 pt-3 space-y-3">
                {ticket.description && (
                  <p className="text-body text-label-secondary whitespace-pre-wrap">{ticket.description}</p>
                )}

                {/* Resolution notes */}
                <div>
                  <label className="text-caption-1 text-label-secondary">Resolution Notes</label>
                  <textarea
                    className="mt-1 w-full rounded-xl bg-bg-primary border border-separator/40 px-3 py-2 text-body text-label-primary placeholder:text-label-quaternary focus:outline-none h-16 resize-none"
                    placeholder="Add resolution notes…"
                    value={resolutionDrafts[ticket.id] ?? ticket.resolution_notes ?? ""}
                    onChange={(e) =>
                      setResolutionDrafts((prev) => ({ ...prev, [ticket.id]: e.target.value }))
                    }
                    onBlur={() => {
                      const notes = resolutionDrafts[ticket.id];
                      if (notes !== undefined && notes !== ticket.resolution_notes) {
                        handlePatch(ticket.id, { resolution_notes: notes });
                      }
                    }}
                  />
                </div>

                {/* Status buttons */}
                <div className="flex gap-2 flex-wrap">
                  {STATUS_ORDER.filter((s) => s !== ticket.status).map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => handlePatch(ticket.id, { status: s })}
                      disabled={patchingTicket === ticket.id}
                      className={cn(
                        "text-caption-2 font-semibold rounded-full px-3 py-1 active:scale-95 disabled:opacity-50",
                        statusBadge(s),
                      )}
                    >
                      → {statusLabel(s)}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Notes Tab ─────────────────────────────────────────────────────────────────

function NotesTab({ accountId }: { accountId: string }) {
  const [noteText, setNoteText] = React.useState("");
  const { data, isLoading, error } = useCustomerNotes(accountId);
  const addNote = useAddNote(accountId);

  async function handleAddNote() {
    if (!noteText.trim()) return;
    try {
      await addNote.mutateAsync({ text: noteText });
      setNoteText("");
    } catch (_) {}
  }

  const notes = data?.items ?? [];

  return (
    <div className="pt-4">
      {/* Add note area */}
      <div className="mb-4 rounded-2xl bg-chrome/80 border border-separator/40 p-3">
        <textarea
          className="w-full bg-transparent text-body text-label-primary placeholder:text-label-quaternary focus:outline-none resize-none min-h-[60px]"
          placeholder="Add a note…"
          value={noteText}
          onChange={(e) => setNoteText(e.target.value)}
        />
        <div className="flex justify-end mt-2">
          <button
            type="button"
            onClick={handleAddNote}
            disabled={!noteText.trim() || addNote.isPending}
            className="text-caption-1 font-semibold text-accent bg-accent/10 rounded-full px-4 py-1.5 active:scale-95 disabled:opacity-50"
          >
            {addNote.isPending ? "Saving…" : "Add Note"}
          </button>
        </div>
        {addNote.isError && (
          <p className="text-caption-1 text-red-400 mt-1">{addNote.error?.message}</p>
        )}
      </div>

      {error && <ErrorBanner message={error.message} />}
      {isLoading && (
        <div className="space-y-2">
          {[1, 2].map((i) => (
            <div key={i} className="h-16 rounded-2xl bg-chrome/60 animate-pulse" />
          ))}
        </div>
      )}

      {!isLoading && notes.length === 0 && (
        <p className="text-body text-label-tertiary text-center py-10">No notes yet.</p>
      )}

      {notes.map((note) => (
        <div
          key={note.id}
          className="rounded-2xl bg-chrome/80 border border-separator/40 px-4 py-3 mb-3"
        >
          <p className="text-body text-label-primary whitespace-pre-wrap">{note.text}</p>
          <p className="text-caption-2 text-label-quaternary mt-1.5">
            {note.created_by && <span>{note.created_by} · </span>}
            {fmtDateTime(note.created_at)}
          </p>
        </div>
      ))}
    </div>
  );
}

// ── Details Tab ───────────────────────────────────────────────────────────────

function DetailsTab({ customer }: { customer: CustomerDetail }) {
  const updateCustomer = useUpdateCustomer(customer.id);
  const { data: campuses } = useCampuses();
  const [campusId, setCampusId] = React.useState(customer.campus_id ?? "");
  const [assigningCampus, setAssigningCampus] = React.useState(false);
  const [name, setName] = React.useState(customer.name);
  const [industry, setIndustry] = React.useState(customer.industry ?? "");
  const [website, setWebsite] = React.useState(customer.website ?? "");
  const [city, setCity] = React.useState(customer.hq_city ?? "");
  const [state, setState] = React.useState(customer.hq_state ?? "");
  const [contactName, setContactName] = React.useState(customer.primary_contact_name ?? "");
  const [contactEmail, setContactEmail] = React.useState(customer.primary_contact_email ?? "");
  const [contactPhone, setContactPhone] = React.useState(customer.primary_contact_phone ?? "");
  const [type, setType] = React.useState(customer.type);
  const [saving, setSaving] = React.useState(false);
  const [saved, setSaved] = React.useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      await updateCustomer.mutateAsync({
        name, industry: industry || undefined, website: website || undefined,
        hq_city: city || undefined, hq_state: state || undefined,
        primary_contact_name: contactName || undefined,
        primary_contact_email: contactEmail || undefined,
        primary_contact_phone: contactPhone || undefined,
        type,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  }

  async function handleAssignCampus(value: string) {
    setCampusId(value);
    setAssigningCampus(true);
    try {
      // Empty string clears the link (null); otherwise link the selected campus.
      await updateCustomer.mutateAsync({ campus_id: value || null });
    } finally {
      setAssigningCampus(false);
    }
  }

  function FieldRow({ label, value, onChange, placeholder }: {
    label: string;
    value: string;
    onChange: (v: string) => void;
    placeholder?: string;
  }) {
    return (
      <div className="mb-3">
        <label className="text-caption-1 text-label-secondary">{label}</label>
        <input
          className="mt-1 w-full rounded-xl bg-chrome/80 border border-separator/40 px-3 py-2 text-body text-label-primary placeholder:text-label-quaternary focus:outline-none focus:border-accent/60"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
        />
      </div>
    );
  }

  return (
    <div className="pt-4">
      {/* Account */}
      <p className="text-footnote font-semibold text-label-tertiary uppercase tracking-wide mb-2">Account</p>
      <FieldRow label="Name" value={name} onChange={setName} />
      <div className="mb-3">
        <label className="text-caption-1 text-label-secondary">Type</label>
        <select
          className="mt-1 w-full rounded-xl bg-chrome/80 border border-separator/40 px-3 py-2 text-body text-label-primary focus:outline-none"
          value={type}
          onChange={(e) => setType(e.target.value)}
        >
          <option value="prospect">Prospect</option>
          <option value="customer">Customer</option>
        </select>
      </div>
      <FieldRow label="Industry" value={industry} onChange={setIndustry} placeholder="e.g. AI/HPC" />
      <FieldRow label="Website" value={website} onChange={setWebsite} placeholder="https://" />
      <div className="flex gap-2 mb-3">
        <div className="flex-1">
          <label className="text-caption-1 text-label-secondary">City</label>
          <input
            className="mt-1 w-full rounded-xl bg-chrome/80 border border-separator/40 px-3 py-2 text-body text-label-primary focus:outline-none"
            value={city}
            onChange={(e) => setCity(e.target.value)}
          />
        </div>
        <div className="w-24">
          <label className="text-caption-1 text-label-secondary">State</label>
          <input
            className="mt-1 w-full rounded-xl bg-chrome/80 border border-separator/40 px-3 py-2 text-body text-label-primary focus:outline-none"
            value={state}
            onChange={(e) => setState(e.target.value)}
          />
        </div>
      </div>

      {/* Contact */}
      <p className="text-footnote font-semibold text-label-tertiary uppercase tracking-wide mb-2 mt-4">Contact</p>
      <FieldRow label="Name" value={contactName} onChange={setContactName} />
      <FieldRow label="Email" value={contactEmail} onChange={setContactEmail} placeholder="contact@example.com" />
      <FieldRow label="Phone" value={contactPhone} onChange={setContactPhone} placeholder="+1 (555) 000-0000" />

      {/* Linked Campus & Deal */}
      <p className="text-footnote font-semibold text-label-tertiary uppercase tracking-wide mb-2 mt-4">Linked</p>
      <div className="rounded-2xl bg-chrome/80 border border-separator/40 p-3 mb-3">
        <div className="flex items-center justify-between mb-1">
          <p className="text-caption-1 text-label-secondary">Assign Campus</p>
          {assigningCampus && <Loader2 className="h-3.5 w-3.5 animate-spin text-label-tertiary" />}
        </div>
        <select
          className="w-full rounded-xl bg-chrome/80 border border-separator/40 px-3 py-2 text-body text-label-primary focus:outline-none"
          value={campusId}
          disabled={assigningCampus}
          onChange={(e) => handleAssignCampus(e.target.value)}
        >
          <option value="">No campus linked</option>
          {(campuses?.items ?? []).map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </div>
      <div className="rounded-2xl bg-chrome/80 border border-separator/40 p-3 mb-4">
        <p className="text-caption-1 text-label-secondary mb-1">Most Recent Won Deal</p>
        {customer.won_deal ? (
          <>
            <p className="text-body text-label-primary">{customer.won_deal.name}</p>
            <p className="text-caption-1 text-green-400 mt-0.5 capitalize">{customer.won_deal.stage}</p>
          </>
        ) : (
          <p className="text-body text-label-tertiary">No won deal</p>
        )}
      </div>

      {/* Portal Access — Sprint 4B */}
      <p className="text-footnote font-semibold text-label-tertiary uppercase tracking-wide mb-2 mt-4">Portal Access</p>
      <div className="rounded-2xl bg-chrome/80 border border-separator/40 p-3 mb-4 space-y-2">
        <div className="flex items-center gap-2">
          <span
            className={`text-caption-1 font-semibold rounded-full px-2 py-0.5 ${
              customer.type === "customer"
                ? "bg-green-500/20 text-green-400"
                : "bg-yellow-500/20 text-yellow-400"
            }`}
          >
            {customer.type === "customer" ? "Portal Access Enabled" : "Portal Access Not Active"}
          </span>
        </div>
        {customer.type === "customer" && (
          <>
            <div>
              <p className="text-caption-1 text-label-secondary">Login Email</p>
              <p className="text-body text-label-primary font-medium">
                {customer.primary_contact_email ?? "—"}
              </p>
            </div>
            <button
              type="button"
              onClick={() => {
                navigator.clipboard
                  .writeText("https://quillpm.com/portal/login")
                  .then(() => alert("Portal URL copied!"))
                  .catch(() => {});
              }}
              className="flex items-center gap-1.5 text-caption-1 font-semibold text-accent bg-accent/10 rounded-full px-3 py-1.5 active:scale-95"
            >
              Copy Portal Login URL
            </button>
          </>
        )}
        {customer.type !== "customer" && (
          <p className="text-caption-1 text-label-tertiary">
            Set account type to &ldquo;Customer&rdquo; to enable portal access.
          </p>
        )}
      </div>

      {/* Save */}
      <button
        type="button"
        onClick={handleSave}
        disabled={saving}
        className="w-full rounded-xl bg-accent text-white font-semibold py-3 active:scale-98 disabled:opacity-50 mb-6"
      >
        {saving ? "Saving…" : saved ? "Saved ✓" : "Save Changes"}
      </button>
      {updateCustomer.isError && (
        <p className="text-caption-1 text-red-400">{updateCustomer.error?.message}</p>
      )}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function CustomerDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [tab, setTab] = React.useState<TabKey>("tickets");

  const { data: customerRaw, isLoading, error } = useCustomer(id ?? "");
  const customer = customerRaw as CustomerDetail | undefined;

  if (!id) return null;

  const score = customer?.health?.total ?? null;

  return (
    <MobileShell>
      <TopBar
        title={customer?.name ?? "Customer"}
        left={
          <button type="button" onClick={() => router.push("/customers")} aria-label="Back">
            <ArrowLeft className="w-5 h-5 text-accent" />
          </button>
        }
      />

      <div className="px-4 pb-safe-bottom overflow-y-auto">
        {error && <ErrorBanner message={error.message} />}

        {isLoading && (
          <div className="mt-6 space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-16 rounded-2xl bg-chrome/60 animate-pulse" />
            ))}
          </div>
        )}

        {!isLoading && customer && (
          <>
            {/* Header */}
            <div className="mt-4 rounded-2xl bg-chrome/80 border border-separator/40 p-4 mb-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-title-3 font-bold text-label-primary">{customer.name}</p>
                  <span className="inline-block mt-1 text-caption-2 font-semibold text-accent bg-accent/10 rounded-full px-2 py-0.5">
                    Customer
                  </span>
                  {customer.won_deal?.campus_id && (
                    <span className="ml-2 text-caption-2 text-label-secondary">
                      Campus: {customer.won_deal.campus_id.slice(0, 8)}…
                    </span>
                  )}
                </div>
                <div className="text-right">
                  <p className={cn("text-title-1 font-bold", healthColor(score))}>
                    {score != null ? score : "—"}
                  </p>
                  <p className="text-caption-2 text-label-tertiary">Health</p>
                </div>
              </div>
            </div>

            {/* Tab bar */}
            <div className="flex bg-chrome/60 rounded-2xl p-1 mb-2 border border-separator/30">
              {TABS.map((t) => {
                const Icon = t.icon;
                return (
                  <button
                    key={t.key}
                    type="button"
                    onClick={() => setTab(t.key)}
                    className={cn(
                      "flex-1 flex items-center justify-center gap-1.5 rounded-xl py-2 text-caption-1 font-semibold transition-all",
                      tab === t.key
                        ? "bg-accent/20 text-accent"
                        : "text-label-secondary",
                    )}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    {t.label}
                  </button>
                );
              })}
            </div>

            {/* Tab content */}
            {tab === "tickets" && <TicketsTab accountId={id} />}
            {tab === "notes" && <NotesTab accountId={id} />}
            {tab === "details" && <DetailsTab customer={customer} />}
          </>
        )}
      </div>
    </MobileShell>
  );
}
