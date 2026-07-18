"use client";

/**
 * /customers/[id] — Customer Detail Page
 *
 * Ported visual layer from Lovable: quill-platform-builder/src/routes/customers.$id.tsx
 * Data wiring kept from prod; routing via next/navigation.
 *
 * Key token mappings (LOVABLE_PORT_CONTRACT § Known token equivalences):
 *   bg-bg-elevated shadow-card        — card surfaces
 *   text-success / text-warning / text-danger — semantic colors (exist in prod)
 *   text-primary-foreground           — prod alias for #FFFFFF (accent button text)
 *   bg-fill-quaternary                — no prod equiv → bg-chrome/60
 *   bg-chrome border border-hairline  — modal background
 *   shadow-elevated / accent-pressed  — exist in prod
 *   No inline hex. No emojis.
 */

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  Loader2,
  Plus,
  Settings2,
  StickyNote,
  Ticket,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { healthColor } from "@/components/customers/CustomerCard";
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
import type { CustomerDetail, SupportTicket } from "@/lib/schemas";

// ── Helpers ───────────────────────────────────────────────────────────────────

const TICKET_SEVERITIES = ["P1", "P2", "P3", "P4"] as const;
type TicketSeverity = typeof TICKET_SEVERITIES[number];
type TicketStatus = "open" | "in_progress" | "resolved" | "closed";

function severityCls(sev: string): string {
  switch (sev) {
    case "P1": return "bg-danger text-white";
    case "P2": return "bg-warning text-white";
    case "P3": return "bg-fill-quaternary text-label-secondary";
    default:   return "bg-fill-quaternary text-label-secondary";
  }
}

function statusBadge(s: string): string {
  switch (s) {
    case "open":        return "text-danger bg-danger/10";
    case "in_progress": return "text-warning bg-warning/10";
    case "resolved":    return "text-success bg-success/10";
    case "closed":      return "text-label-tertiary bg-chrome/60";
    default:            return "text-label-secondary bg-chrome/60";
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

const inputCls =
  "w-full rounded-xl bg-bg-elevated shadow-card px-3 py-2.5 text-body text-label-primary placeholder:text-label-tertiary focus:outline-none focus:border-accent";

// ── Tabs ──────────────────────────────────────────────────────────────────────

type TabValue = "tickets" | "notes" | "details";

const TABS: { value: TabValue; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { value: "tickets", label: "Tickets", icon: Ticket },
  { value: "notes", label: "Notes", icon: StickyNote },
  { value: "details", label: "Details", icon: Settings2 },
];

// ── TicketRow (owns its own useUpdateTicket at the component level) ────────────

const STATUS_ORDER: TicketStatus[] = ["open", "in_progress", "resolved", "closed"];

function TicketRow({
  ticket,
  accountId,
  expanded,
  onToggle,
}: {
  ticket: SupportTicket;
  accountId: string;
  expanded: boolean;
  onToggle: () => void;
}) {
  const updateTicket = useUpdateTicket(accountId, ticket.id);
  const [notes, setNotes] = React.useState(ticket.resolution_notes ?? "");

  React.useEffect(() => {
    setNotes(ticket.resolution_notes ?? "");
  }, [ticket.resolution_notes]);

  return (
    <div
      className={cn(
        "rounded-2xl bg-bg-elevated shadow-card overflow-hidden",
        expanded && "border border-accent/30",
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-start gap-3 px-4 py-3 text-left no-tap-highlight active:opacity-70"
      >
        <span
          className={cn(
            "rounded px-1.5 py-0.5 text-caption-2 font-bold shrink-0 mt-0.5",
            severityCls(ticket.severity),
          )}
        >
          {ticket.severity}
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-body font-medium text-label-primary truncate">{ticket.title}</p>
          <div className="flex items-center gap-2 mt-1">
            <span className={cn("text-caption-2 font-semibold rounded-full px-1.5 py-0.5", statusBadge(ticket.status))}>
              {statusLabel(ticket.status)}
            </span>
            <span className="text-caption-2 text-label-tertiary">{fmtDate(ticket.created_at)}</span>
          </div>
        </div>
        {expanded ? (
          <ChevronDown className="h-4 w-4 text-label-tertiary shrink-0 mt-1" />
        ) : (
          <ChevronRight className="h-4 w-4 text-label-tertiary shrink-0 mt-1" />
        )}
      </button>

      {expanded && (
        <div className="px-4 pb-4 border-t border-hairline pt-3 flex flex-col gap-3">
          {ticket.description && (
            <p className="text-body text-label-secondary whitespace-pre-wrap">{ticket.description}</p>
          )}
          {ticket.resolved_at && (
            <p className="text-caption-1 text-success">Resolved {fmtDate(ticket.resolved_at)}</p>
          )}
          <div className="flex flex-col gap-1">
            <label className="text-caption-1 text-label-secondary">Resolution Notes</label>
            <textarea
              className={cn(inputCls, "resize-none")}
              rows={2}
              placeholder="Add resolution notes…"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              onBlur={() => {
                if (notes !== (ticket.resolution_notes ?? "")) {
                  updateTicket.mutate({ resolution_notes: notes });
                }
              }}
            />
          </div>
          <div className="flex gap-2 flex-wrap">
            {STATUS_ORDER.filter((s) => s !== ticket.status).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => updateTicket.mutate({ status: s })}
                disabled={updateTicket.isPending}
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
}

// ── New Ticket Modal ──────────────────────────────────────────────────────────

function NewTicketModal({ accountId, onClose }: { accountId: string; onClose: () => void }) {
  const createTicket = useCreateTicket(accountId);
  const [title, setTitle] = React.useState("");
  const [severity, setSeverity] = React.useState<TicketSeverity>("P3");
  const [description, setDescription] = React.useState("");
  const [formError, setFormError] = React.useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    setFormError(null);
    try {
      await createTicket.mutateAsync({
        title: title.trim(),
        severity,
        description: description.trim() || undefined,
      });
      onClose();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to create ticket");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 backdrop-blur-sm sm:items-center">
      <div className="w-full max-w-lg rounded-t-2xl sm:rounded-2xl bg-chrome border border-hairline shadow-2xl pb-safe">
        <div className="flex items-center justify-between px-4 pt-4 pb-2 border-b border-hairline">
          <h2 className="text-headline font-semibold text-label-primary">New Ticket</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="text-label-secondary active:text-label-primary"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3 px-4 py-4">
          {formError && (
            <p className="text-caption-1 text-danger bg-danger/10 rounded-xl px-3 py-2">{formError}</p>
          )}
          <label className="flex flex-col gap-1">
            <span className="text-caption-1 text-label-secondary">Title *</span>
            <input
              className={inputCls}
              placeholder="Describe the issue…"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-caption-1 text-label-secondary">Severity</span>
            <select
              className={inputCls}
              value={severity}
              onChange={(e) => setSeverity(e.target.value as TicketSeverity)}
            >
              {TICKET_SEVERITIES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-caption-1 text-label-secondary">Description (optional)</span>
            <textarea
              className={cn(inputCls, "resize-none")}
              rows={3}
              placeholder="Additional context…"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>
          <button
            type="submit"
            disabled={!title.trim() || createTicket.isPending}
            className="mt-2 w-full rounded-xl py-3 text-body font-semibold bg-accent text-primary-foreground disabled:opacity-40"
          >
            {createTicket.isPending ? "Creating…" : "Create Ticket"}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── Tickets Tab ───────────────────────────────────────────────────────────────

function TicketsTab({ accountId }: { accountId: string }) {
  const { data, isLoading } = useCustomerTickets(accountId);
  const [expanded, setExpanded] = React.useState<string | null>(null);
  const [showNew, setShowNew] = React.useState(false);

  // prod envelope: data is TicketListPage | undefined → .items
  const tickets = data?.items ?? [];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-caption-1 text-label-secondary">
          {tickets.length} ticket{tickets.length !== 1 ? "s" : ""}
        </span>
        <button
          type="button"
          onClick={() => setShowNew(true)}
          className="flex items-center gap-1.5 rounded-full bg-accent/10 text-accent active:bg-accent/20 active:scale-[0.98] transition-all px-3 py-1.5 text-caption-1 font-semibold"
        >
          <Plus className="h-4 w-4" />
          New Ticket
        </button>
      </div>

      {isLoading && (
        <div className="flex justify-center py-6 text-label-tertiary">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      )}

      {!isLoading && tickets.length === 0 && (
        <p className="text-body text-label-tertiary text-center py-10">No tickets yet.</p>
      )}

      {tickets.map((t) => (
        <TicketRow
          key={t.id}
          ticket={t}
          accountId={accountId}
          expanded={expanded === t.id}
          onToggle={() => setExpanded(expanded === t.id ? null : t.id)}
        />
      ))}

      {showNew && <NewTicketModal accountId={accountId} onClose={() => setShowNew(false)} />}
    </div>
  );
}

// ── Notes Tab ─────────────────────────────────────────────────────────────────

function NotesTab({ accountId }: { accountId: string }) {
  const { data, isLoading } = useCustomerNotes(accountId);
  const addNote = useAddNote(accountId);
  const [text, setText] = React.useState("");

  // prod envelope: data is NoteListPage | undefined → .items
  const notes = data?.items ?? [];

  async function handleAdd() {
    if (!text.trim()) return;
    try {
      await addNote.mutateAsync({ text: text.trim() });
      setText("");
    } catch {
      // ignore
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-2xl bg-bg-elevated shadow-card p-3">
        <textarea
          className="w-full bg-transparent text-body text-label-primary placeholder:text-label-tertiary focus:outline-none resize-none min-h-[60px]"
          placeholder="Add a note…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="flex justify-end mt-2">
          <button
            type="button"
            onClick={handleAdd}
            disabled={!text.trim() || addNote.isPending}
            className="text-caption-1 font-semibold text-accent bg-accent/10 rounded-full px-4 py-1.5 disabled:opacity-50"
          >
            {addNote.isPending ? "Saving…" : "Add Note"}
          </button>
        </div>
        {addNote.isError && (
          <p className="text-caption-1 text-danger mt-1">{addNote.error?.message}</p>
        )}
      </div>

      {isLoading && (
        <div className="flex justify-center py-4 text-label-tertiary">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      )}

      {!isLoading && notes.length === 0 && (
        <p className="text-body text-label-tertiary text-center py-6">No notes yet.</p>
      )}

      {notes.map((n) => (
        <div key={n.id} className="rounded-2xl bg-bg-elevated shadow-card px-4 py-3">
          <p className="text-body text-label-primary whitespace-pre-wrap">{n.text}</p>
          <p className="text-caption-2 text-label-tertiary mt-1.5">
            {n.created_by && <span>{n.created_by} · </span>}
            {fmtDateTime(n.created_at)}
          </p>
        </div>
      ))}
    </div>
  );
}

// ── Details Tab ───────────────────────────────────────────────────────────────

function SectionHeader({ title }: { title: string }) {
  return (
    <p className="text-footnote font-semibold text-label-tertiary uppercase tracking-wide mt-2">
      {title}
    </p>
  );
}

function FieldRow({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-caption-1 text-label-secondary">{label}</span>
      <input
        className={inputCls}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </label>
  );
}

function DetailsTab({ customer }: { customer: CustomerDetail }) {
  const updateCustomer = useUpdateCustomer(customer.id);
  const { data: campuses } = useCampuses();

  const [name, setName] = React.useState(customer.name);
  const [type, setType] = React.useState(customer.type);
  const [industry, setIndustry] = React.useState(customer.industry ?? "");
  const [website, setWebsite] = React.useState(customer.website ?? "");
  const [city, setCity] = React.useState(customer.hq_city ?? "");
  const [state, setState] = React.useState(customer.hq_state ?? "");
  const [contactName, setContactName] = React.useState(customer.primary_contact_name ?? "");
  const [contactEmail, setContactEmail] = React.useState(customer.primary_contact_email ?? "");
  const [contactPhone, setContactPhone] = React.useState(customer.primary_contact_phone ?? "");
  const [campusId, setCampusId] = React.useState(customer.campus_id ?? "");
  const [assigning, setAssigning] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [saved, setSaved] = React.useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      await updateCustomer.mutateAsync({
        name,
        type,
        industry: industry || undefined,
        website: website || undefined,
        hq_city: city || undefined,
        hq_state: state || undefined,
        primary_contact_name: contactName || undefined,
        primary_contact_email: contactEmail || undefined,
        primary_contact_phone: contactPhone || undefined,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  }

  async function handleAssignCampus(value: string) {
    setCampusId(value);
    setAssigning(true);
    try {
      // null clears the link; non-empty string links the campus
      await updateCustomer.mutateAsync({ campus_id: value || null });
    } finally {
      setAssigning(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <SectionHeader title="Account" />
      <FieldRow label="Name" value={name} onChange={setName} />
      <label className="flex flex-col gap-1">
        <span className="text-caption-1 text-label-secondary">Type</span>
        <select
          className={inputCls}
          value={type}
          onChange={(e) => setType(e.target.value)}
        >
          <option value="prospect">Prospect</option>
          <option value="customer">Customer</option>
        </select>
      </label>
      <FieldRow label="Industry" value={industry} onChange={setIndustry} placeholder="e.g. AI/HPC" />
      <FieldRow label="Website" value={website} onChange={setWebsite} placeholder="https://" />
      <div className="grid grid-cols-[1fr_6rem] gap-2">
        <FieldRow label="City" value={city} onChange={setCity} />
        <FieldRow label="State" value={state} onChange={setState} />
      </div>

      <SectionHeader title="Contact" />
      <FieldRow label="Name" value={contactName} onChange={setContactName} />
      <FieldRow label="Email" value={contactEmail} onChange={setContactEmail} placeholder="contact@example.com" />
      <FieldRow label="Phone" value={contactPhone} onChange={setContactPhone} placeholder="+1 (555) 000-0000" />

      <SectionHeader title="Linked" />
      <div className="rounded-2xl bg-bg-elevated shadow-card p-3">
        <div className="flex items-center justify-between mb-1">
          <p className="text-caption-1 text-label-secondary">Assign Campus</p>
          {assigning && <Loader2 className="h-3.5 w-3.5 animate-spin text-label-tertiary" />}
        </div>
        <select
          className={inputCls}
          value={campusId}
          disabled={assigning}
          onChange={(e) => handleAssignCampus(e.target.value)}
        >
          <option value="">No campus linked</option>
          {/* prod envelope: CampusListResponse.items */}
          {(campuses?.items ?? []).map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </div>
      <div className="rounded-2xl bg-bg-elevated shadow-card p-3">
        <p className="text-caption-1 text-label-secondary mb-1">Most Recent Won Deal</p>
        {customer.won_deal ? (
          <>
            <p className="text-body text-label-primary">{customer.won_deal.name}</p>
            <p className="text-caption-1 text-success mt-0.5 capitalize">{customer.won_deal.stage}</p>
          </>
        ) : (
          <p className="text-body text-label-tertiary">No won deal</p>
        )}
      </div>

      {/* Portal Access — Sprint 4B */}
      <SectionHeader title="Portal Access" />
      <div className="rounded-2xl bg-bg-elevated shadow-card p-3 flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <span
            className={`text-caption-1 font-semibold rounded-full px-2 py-0.5 ${
              customer.type === "customer"
                ? "bg-success/20 text-success"
                : "bg-warning/20 text-warning"
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

      <button
        type="button"
        onClick={handleSave}
        disabled={saving}
        className="mt-2 w-full rounded-full bg-accent text-primary-foreground shadow-card hover:bg-accent-pressed hover:shadow-elevated active:scale-[0.98] transition-all font-semibold py-3 disabled:opacity-50"
      >
        {saving ? "Saving…" : saved ? "Saved" : "Save Changes"}
      </button>
      {updateCustomer.isError && (
        <p className="text-caption-1 text-danger">{updateCustomer.error?.message}</p>
      )}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

function CustomerDetailPageInner() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [tab, setTab] = React.useState<TabValue>("tickets");

  const { data: customerRaw, isLoading, error } = useCustomer(id ?? "");
  const customer = customerRaw as CustomerDetail | undefined;

  if (!id) return null;

  const score = customer?.health?.total ?? null;

  return (
    <MobileShell>
      <TopBar
        title={customer?.name ?? "Customer"}
        right={
          <button
            type="button"
            aria-label="Back to customers"
            onClick={() => router.push("/customers")}
            className="flex items-center gap-1 text-callout font-semibold text-accent"
          >
            <ArrowLeft className="h-4 w-4" />
            Back
          </button>
        }
      />

      <div className="mx-auto w-full max-w-[708px] px-4 pt-3 pb-16 md:max-w-4xl md:px-8">
        {isLoading && (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-label-quaternary" />
          </div>
        )}

        {error && (
          <div className="rounded-xl border border-danger/30 bg-danger/10 p-3 text-callout text-danger">
            Failed to load this customer.
          </div>
        )}

        {customer && (
          <div className="flex flex-col gap-4">
            {/* Header card */}
            <div className="rounded-2xl bg-bg-elevated shadow-card p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-title-3 font-bold text-label-primary truncate">
                    {customer.name}
                  </p>
                  <span className="inline-block mt-1 text-caption-2 font-semibold text-accent bg-accent/10 rounded-full px-2 py-0.5 capitalize">
                    {customer.type}
                  </span>
                  {customer.industry && (
                    <p className="text-caption-1 text-label-secondary mt-1">
                      {customer.industry}
                    </p>
                  )}
                </div>
                <div className="text-right shrink-0">
                  <p className={cn("text-title-1 font-bold", healthColor(score))}>
                    {score != null ? score : "—"}
                  </p>
                  <p className="text-caption-2 text-label-tertiary">Health</p>
                </div>
              </div>
            </div>

            {/* Tab bar — bg-fill-quaternary → bg-chrome/60 (no prod equiv) */}
            <div className="flex gap-1 rounded-xl bg-chrome/60 p-1">
              {TABS.map((t) => {
                const Icon = t.icon;
                return (
                  <button
                    key={t.value}
                    type="button"
                    onClick={() => setTab(t.value)}
                    className={cn(
                      "flex-1 flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-caption-1 font-semibold transition-colors",
                      tab === t.value
                        ? "bg-bg text-label-primary shadow"
                        : "text-label-secondary active:opacity-70",
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {t.label}
                  </button>
                );
              })}
            </div>

            {/* Tab content */}
            <div className="pt-1">
              {tab === "tickets" && <TicketsTab accountId={id} />}
              {tab === "notes" && <NotesTab accountId={id} />}
              {tab === "details" && <DetailsTab customer={customer} />}
            </div>
          </div>
        )}
      </div>
    </MobileShell>
  );
}

export default function CustomerDetailPage() {
  return (
    <ErrorBoundary moduleName="Customers">
      <CustomerDetailPageInner />
    </ErrorBoundary>
  );
}
