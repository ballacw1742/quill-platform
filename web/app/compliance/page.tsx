"use client";

/**
 * /compliance — Compliance Register (Sprint 4A)
 *
 * Division 8: Tracks contract obligations, regulatory filings, insurance policies,
 * and compliance checklists (SOC 2, ISO 27001, FISMA, NIST).
 *
 * Design: dark Quill chrome, accent blue #0A84FF, matches /finance and /supply-chain.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Clock,
  FileCheck,
  Plus,
  Shield,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import {
  useComplianceSummary,
  useComplianceUpcoming,
  useObligations,
  useRegulatoryItems,
  useInsurancePolicies,
  useChecklists,
  useCreateObligation,
  useCreateRegulatoryItem,
  useCreateInsurancePolicy,
  useCreateChecklist,
  useUpdateObligation,
  useUpdateRegulatoryItem,
} from "@/lib/api";
import type {
  Obligation,
  RegulatoryItem,
  InsurancePolicy,
  Checklist,
  UpcomingDeadline,
  ComplianceSummary,
} from "@/lib/schemas";
import {
  OBLIGATION_TYPES,
  OBLIGATION_STATUSES,
  REGULATORY_FRAMEWORKS,
  REGULATORY_STATUSES,
  INSURANCE_TYPES,
  INSURANCE_STATUSES,
  CHECKLIST_FRAMEWORKS,
} from "@/lib/schemas";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function fmtUSD(v: number | null | undefined): string {
  if (v == null) return "—";
  if (Math.abs(v) >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(1)}B`;
  if (Math.abs(v) >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
  return `$${v.toLocaleString()}`;
}

function daysLabel(d: string | null | undefined): { label: string; isOverdue: boolean } {
  if (!d) return { label: "No due date", isOverdue: false };
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const due = new Date(d);
  due.setHours(0, 0, 0, 0);
  const diff = Math.round((due.getTime() - today.getTime()) / 86400000);
  if (diff < 0) return { label: `${Math.abs(diff)}d overdue`, isOverdue: true };
  if (diff === 0) return { label: "Due today", isOverdue: false };
  if (diff === 1) return { label: "Due tomorrow", isOverdue: false };
  return { label: `${diff}d remaining`, isOverdue: false };
}

// ── Status badges ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    open:        { label: "Open",        cls: "text-blue-400 bg-blue-400/10" },
    overdue:     { label: "Overdue",     cls: "text-red-400 bg-red-400/10" },
    complete:    { label: "Complete",    cls: "text-green-400 bg-green-400/10" },
    waived:      { label: "Waived",      cls: "text-zinc-400 bg-zinc-400/10" },
    in_progress: { label: "In Progress", cls: "text-yellow-400 bg-yellow-400/10" },
    active:      { label: "Active",      cls: "text-green-400 bg-green-400/10" },
    expiring:    { label: "Expiring",    cls: "text-orange-400 bg-orange-400/10" },
    expired:     { label: "Expired",     cls: "text-red-400 bg-red-400/10" },
    cancelled:   { label: "Cancelled",   cls: "text-zinc-500 bg-zinc-500/10" },
    archived:    { label: "Archived",    cls: "text-zinc-400 bg-zinc-400/10" },
  };
  const { label, cls } = map[status] ?? { label: status, cls: "text-label-secondary bg-bg-elevated" };
  return (
    <span className={cn("inline-flex items-center rounded-md px-2 py-0.5 text-caption-1 font-medium", cls)}>
      {label}
    </span>
  );
}

function TypeBadge({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center rounded-md px-2 py-0.5 text-caption-1 font-medium text-label-secondary bg-bg-elevated border border-separator/20 uppercase tracking-wide">
      {label.replace(/_/g, " ")}
    </span>
  );
}

// ── Summary card ──────────────────────────────────────────────────────────────

function SummaryCard({
  label,
  value,
  sub,
  color,
  alert,
}: {
  label: string;
  value: string | number;
  sub?: string;
  color: "red" | "orange" | "blue" | "green";
  alert?: boolean;
}) {
  const colorMap = {
    red:    { icon: "text-red-400",    bg: "bg-red-400/10",    border: alert ? "border-red-400/40" : "" },
    orange: { icon: "text-orange-400", bg: "bg-orange-400/10", border: alert ? "border-orange-400/40" : "" },
    blue:   { icon: "text-blue-400",   bg: "bg-blue-400/10",   border: "" },
    green:  { icon: "text-green-400",  bg: "bg-green-400/10",  border: "" },
  };
  const c = colorMap[color];
  return (
    <div className={cn(
      "rounded-2xl bg-bg-secondary border border-separator/30 p-4 flex flex-col gap-1.5",
      c.border,
    )}>
      <span className="text-caption-1 text-label-secondary">{label}</span>
      <span className={cn("text-title-2 font-semibold", c.icon)}>{value}</span>
      {sub && <span className="text-caption-1 text-label-tertiary">{sub}</span>}
    </div>
  );
}

// ── Upcoming deadline row ─────────────────────────────────────────────────────

function DeadlineRow({ item }: { item: UpcomingDeadline }) {
  const typeColors: Record<string, string> = {
    obligation: "text-blue-400",
    regulatory: "text-purple-400",
    insurance:  "text-orange-400",
  };
  const days = item.days_until_due ?? null;
  const isOverdue = days !== null && days < 0;
  const isUrgent = days !== null && days >= 0 && days <= 7;

  return (
    <div className="flex items-center gap-3 px-4 py-3 border-b border-separator/20 last:border-0">
      <div className={cn("shrink-0", typeColors[item.deadline_type] ?? "text-label-tertiary")}>
        <Clock className="h-4 w-4" strokeWidth={1.75} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <TypeBadge label={item.framework_or_type} />
          <span className={cn(
            "text-caption-1 font-medium",
            isOverdue ? "text-red-400" : isUrgent ? "text-orange-400" : "text-label-tertiary",
          )}>
            {days === null ? "—" : isOverdue ? `${Math.abs(days)}d overdue` : days === 0 ? "today" : `${days}d`}
          </span>
        </div>
        <span className="text-callout text-label-primary truncate block">{item.title}</span>
      </div>
      <StatusBadge status={item.status} />
    </div>
  );
}

// ── Tab content: Obligations ──────────────────────────────────────────────────

function ObligationRow({ item }: { item: Obligation }) {
  const [expanded, setExpanded] = React.useState(false);
  const update = useUpdateObligation(item.id);
  const { label: dayLabel, isOverdue } = daysLabel(item.due_date ?? null);

  const markComplete = async () => {
    await update.mutateAsync({ status: "complete" });
  };

  return (
    <div className="border-b border-separator/20 last:border-0">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left active:bg-bg-elevated"
      >
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-0.5">
            <TypeBadge label={item.obligation_type} />
            <StatusBadge status={item.status} />
          </div>
          <div className="text-body font-medium text-label-primary truncate mt-0.5">{item.title}</div>
          {item.due_date && (
            <div className={cn("text-caption-1 mt-0.5", isOverdue ? "text-red-400" : "text-label-secondary")}>
              {fmtDate(item.due_date)} · {dayLabel}
            </div>
          )}
        </div>
        {expanded ? (
          <ChevronUp className="h-4 w-4 text-label-tertiary shrink-0" />
        ) : (
          <ChevronDown className="h-4 w-4 text-label-tertiary shrink-0" />
        )}
      </button>
      {expanded && (
        <div className="px-4 pb-3 space-y-2">
          {item.description && (
            <p className="text-callout text-label-secondary">{item.description}</p>
          )}
          <div className="text-caption-1 text-label-secondary space-y-0.5">
            {item.recurrence && <div>Recurrence: {item.recurrence.replace("_", " ")}</div>}
            {item.contract_id && <div>Contract: {item.contract_id.slice(0, 12)}…</div>}
            {item.notes && <div>Notes: {item.notes}</div>}
          </div>
          {item.status === "open" && (
            <button
              onClick={markComplete}
              disabled={update.isPending}
              className="rounded-xl bg-green-400/10 text-green-400 px-4 py-2 text-callout font-medium active:opacity-70 disabled:opacity-50"
            >
              {update.isPending ? "Updating…" : "Mark Complete"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── Tab content: Regulatory ───────────────────────────────────────────────────

function RegulatoryRow({ item }: { item: RegulatoryItem }) {
  const [expanded, setExpanded] = React.useState(false);
  const update = useUpdateRegulatoryItem(item.id);
  const { label: dayLabel, isOverdue } = daysLabel(item.due_date ?? null);

  return (
    <div className="border-b border-separator/20 last:border-0">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left active:bg-bg-elevated"
      >
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-0.5">
            <TypeBadge label={item.framework} />
            <StatusBadge status={item.status} />
          </div>
          <div className="text-body font-medium text-label-primary truncate mt-0.5">{item.title}</div>
          {item.due_date && (
            <div className={cn("text-caption-1 mt-0.5", isOverdue ? "text-red-400" : "text-label-secondary")}>
              {fmtDate(item.due_date)} · {dayLabel}
            </div>
          )}
          {item.jurisdiction && (
            <div className="text-caption-1 text-label-tertiary">{item.jurisdiction}</div>
          )}
        </div>
        {expanded ? (
          <ChevronUp className="h-4 w-4 text-label-tertiary shrink-0" />
        ) : (
          <ChevronDown className="h-4 w-4 text-label-tertiary shrink-0" />
        )}
      </button>
      {expanded && (
        <div className="px-4 pb-3 space-y-2">
          {item.description && (
            <p className="text-callout text-label-secondary">{item.description}</p>
          )}
          <div className="text-caption-1 text-label-secondary space-y-0.5">
            {item.responsible_party && <div>Owner: {item.responsible_party}</div>}
            {item.recurrence && <div>Recurrence: {item.recurrence.replace("_", " ")}</div>}
            {item.notes && <div>Notes: {item.notes}</div>}
          </div>
          {(item.status === "open" || item.status === "in_progress") && (
            <button
              onClick={() => update.mutateAsync({ status: "complete" })}
              disabled={update.isPending}
              className="rounded-xl bg-green-400/10 text-green-400 px-4 py-2 text-callout font-medium active:opacity-70 disabled:opacity-50"
            >
              {update.isPending ? "Updating…" : "Mark Complete"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── Tab content: Insurance ────────────────────────────────────────────────────

function InsuranceRow({ item }: { item: InsurancePolicy }) {
  const [expanded, setExpanded] = React.useState(false);
  const { label: dayLabel, isOverdue } = daysLabel(item.expiry_date ?? null);

  return (
    <div className="border-b border-separator/20 last:border-0">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left active:bg-bg-elevated"
      >
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-0.5">
            <TypeBadge label={item.policy_type} />
            <StatusBadge status={item.status} />
          </div>
          <div className="text-body font-medium text-label-primary truncate mt-0.5">{item.policy_name}</div>
          <div className="flex gap-3 text-caption-1 text-label-secondary mt-0.5">
            {item.carrier && <span>{item.carrier}</span>}
            {item.expiry_date && (
              <span className={isOverdue ? "text-red-400" : ""}>
                Expires {fmtDate(item.expiry_date)} · {dayLabel}
              </span>
            )}
          </div>
        </div>
        {expanded ? (
          <ChevronUp className="h-4 w-4 text-label-tertiary shrink-0" />
        ) : (
          <ChevronDown className="h-4 w-4 text-label-tertiary shrink-0" />
        )}
      </button>
      {expanded && (
        <div className="px-4 pb-3 space-y-1.5">
          <div className="text-caption-1 text-label-secondary space-y-0.5">
            {item.policy_number && <div>Policy #: {item.policy_number}</div>}
            {item.coverage_amount_usd != null && (
              <div>Coverage: {fmtUSD(item.coverage_amount_usd)}</div>
            )}
            {item.premium_annual_usd != null && (
              <div>Annual Premium: {fmtUSD(item.premium_annual_usd)}</div>
            )}
            {item.effective_date && <div>Effective: {fmtDate(item.effective_date)}</div>}
            {item.notes && <div>Notes: {item.notes}</div>}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Tab content: Checklists ───────────────────────────────────────────────────

function ChecklistCard({ item }: { item: Checklist }) {
  const router = useRouter();
  return (
    <button
      type="button"
      onClick={() => router.push(`/compliance/checklists/${item.id}`)}
      className="w-full flex items-center gap-3 px-4 py-3 text-left active:bg-bg-elevated border-b border-separator/20 last:border-0"
    >
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2 mb-0.5">
          <TypeBadge label={item.framework} />
          <StatusBadge status={item.status} />
        </div>
        <div className="text-body font-medium text-label-primary mt-0.5">{item.name}</div>
        {item.campus_id && (
          <div className="text-caption-1 text-label-tertiary">Campus: {item.campus_id.slice(0, 12)}…</div>
        )}
      </div>
      <ChevronRight className="h-4 w-4 text-label-tertiary shrink-0" />
    </button>
  );
}

// ── Modals ────────────────────────────────────────────────────────────────────

function NewObligationModal({ onClose }: { onClose: () => void }) {
  const create = useCreateObligation();
  const [form, setForm] = React.useState({
    title: "",
    obligation_type: "other",
    status: "open",
    due_date: "",
    recurrence: "",
    notes: "",
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.title) return;
    await create.mutateAsync({
      title: form.title,
      obligation_type: form.obligation_type,
      status: form.status,
      due_date: form.due_date || undefined,
      recurrence: form.recurrence || undefined,
      notes: form.notes || undefined,
    });
    onClose();
  };

  return (
    <ModalShell title="New Obligation" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <FieldInput label="Title *" value={form.title} onChange={(v) => setForm((f) => ({ ...f, title: v }))} placeholder="e.g. Q3 FERC reporting" required />
        <FieldSelect label="Type" value={form.obligation_type} onChange={(v) => setForm((f) => ({ ...f, obligation_type: v }))}>
          {OBLIGATION_TYPES.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
        </FieldSelect>
        <FieldSelect label="Status" value={form.status} onChange={(v) => setForm((f) => ({ ...f, status: v }))}>
          {OBLIGATION_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </FieldSelect>
        <FieldInput type="date" label="Due Date" value={form.due_date} onChange={(v) => setForm((f) => ({ ...f, due_date: v }))} />
        <FieldInput label="Notes" value={form.notes} onChange={(v) => setForm((f) => ({ ...f, notes: v }))} placeholder="Optional" />
        <SubmitBtn loading={create.isPending} label="Add Obligation" />
      </form>
    </ModalShell>
  );
}

function NewRegulatoryModal({ onClose }: { onClose: () => void }) {
  const create = useCreateRegulatoryItem();
  const [form, setForm] = React.useState({
    title: "",
    framework: "other",
    status: "open",
    jurisdiction: "",
    due_date: "",
    responsible_party: "",
    notes: "",
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.title) return;
    await create.mutateAsync({
      title: form.title,
      framework: form.framework,
      status: form.status,
      jurisdiction: form.jurisdiction || undefined,
      due_date: form.due_date || undefined,
      responsible_party: form.responsible_party || undefined,
      notes: form.notes || undefined,
    });
    onClose();
  };

  return (
    <ModalShell title="New Regulatory Item" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <FieldInput label="Title *" value={form.title} onChange={(v) => setForm((f) => ({ ...f, title: v }))} placeholder="e.g. FERC Order 889 Annual Filing" required />
        <FieldSelect label="Framework" value={form.framework} onChange={(v) => setForm((f) => ({ ...f, framework: v }))}>
          {REGULATORY_FRAMEWORKS.map((t) => <option key={t} value={t}>{t.toUpperCase()}</option>)}
        </FieldSelect>
        <FieldSelect label="Status" value={form.status} onChange={(v) => setForm((f) => ({ ...f, status: v }))}>
          {REGULATORY_STATUSES.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
        </FieldSelect>
        <FieldInput label="Jurisdiction" value={form.jurisdiction} onChange={(v) => setForm((f) => ({ ...f, jurisdiction: v }))} placeholder="e.g. Federal, Ohio" />
        <FieldInput type="date" label="Due Date" value={form.due_date} onChange={(v) => setForm((f) => ({ ...f, due_date: v }))} />
        <FieldInput label="Owner" value={form.responsible_party} onChange={(v) => setForm((f) => ({ ...f, responsible_party: v }))} placeholder="Responsible party" />
        <FieldInput label="Notes" value={form.notes} onChange={(v) => setForm((f) => ({ ...f, notes: v }))} placeholder="Optional" />
        <SubmitBtn loading={create.isPending} label="Add Regulatory Item" />
      </form>
    </ModalShell>
  );
}

function NewInsuranceModal({ onClose }: { onClose: () => void }) {
  const create = useCreateInsurancePolicy();
  const [form, setForm] = React.useState({
    policy_name: "",
    policy_type: "other",
    carrier: "",
    policy_number: "",
    coverage_amount_usd: "",
    premium_annual_usd: "",
    effective_date: "",
    expiry_date: "",
    notes: "",
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.policy_name) return;
    await create.mutateAsync({
      policy_name: form.policy_name,
      policy_type: form.policy_type,
      carrier: form.carrier || undefined,
      policy_number: form.policy_number || undefined,
      coverage_amount_usd: form.coverage_amount_usd ? parseFloat(form.coverage_amount_usd) : undefined,
      premium_annual_usd: form.premium_annual_usd ? parseFloat(form.premium_annual_usd) : undefined,
      effective_date: form.effective_date || undefined,
      expiry_date: form.expiry_date || undefined,
      notes: form.notes || undefined,
    });
    onClose();
  };

  return (
    <ModalShell title="New Insurance Policy" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <FieldInput label="Policy Name *" value={form.policy_name} onChange={(v) => setForm((f) => ({ ...f, policy_name: v }))} placeholder="e.g. Commercial Property 2026" required />
        <FieldSelect label="Type" value={form.policy_type} onChange={(v) => setForm((f) => ({ ...f, policy_type: v }))}>
          {INSURANCE_TYPES.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
        </FieldSelect>
        <FieldInput label="Carrier" value={form.carrier} onChange={(v) => setForm((f) => ({ ...f, carrier: v }))} placeholder="e.g. AIG, Chubb" />
        <FieldInput label="Policy Number" value={form.policy_number} onChange={(v) => setForm((f) => ({ ...f, policy_number: v }))} />
        <div className="grid grid-cols-2 gap-3">
          <FieldInput type="number" label="Coverage (USD)" value={form.coverage_amount_usd} onChange={(v) => setForm((f) => ({ ...f, coverage_amount_usd: v }))} placeholder="0" />
          <FieldInput type="number" label="Annual Premium" value={form.premium_annual_usd} onChange={(v) => setForm((f) => ({ ...f, premium_annual_usd: v }))} placeholder="0" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <FieldInput type="date" label="Effective Date" value={form.effective_date} onChange={(v) => setForm((f) => ({ ...f, effective_date: v }))} />
          <FieldInput type="date" label="Expiry Date" value={form.expiry_date} onChange={(v) => setForm((f) => ({ ...f, expiry_date: v }))} />
        </div>
        <FieldInput label="Notes" value={form.notes} onChange={(v) => setForm((f) => ({ ...f, notes: v }))} placeholder="Optional" />
        <SubmitBtn loading={create.isPending} label="Add Policy" />
      </form>
    </ModalShell>
  );
}

function NewChecklistModal({ onClose }: { onClose: () => void }) {
  const create = useCreateChecklist();
  const [form, setForm] = React.useState({
    name: "",
    framework: "custom",
    campus_id: "",
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name) return;
    await create.mutateAsync({
      name: form.name,
      framework: form.framework,
      campus_id: form.campus_id || undefined,
    });
    onClose();
  };

  return (
    <ModalShell title="New Checklist" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <FieldInput label="Name *" value={form.name} onChange={(v) => setForm((f) => ({ ...f, name: v }))} placeholder="e.g. SOC 2 Type II — FY2026" required />
        <FieldSelect label="Framework" value={form.framework} onChange={(v) => setForm((f) => ({ ...f, framework: v }))}>
          {CHECKLIST_FRAMEWORKS.map((t) => <option key={t} value={t}>{t.toUpperCase()}</option>)}
        </FieldSelect>
        <FieldInput label="Campus" value={form.campus_id} onChange={(v) => setForm((f) => ({ ...f, campus_id: v }))} placeholder="Campus ID (optional)" />
        <SubmitBtn loading={create.isPending} label="Create Checklist" />
      </form>
    </ModalShell>
  );
}

// ── Shared form primitives ────────────────────────────────────────────────────

function ModalShell({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-bg-secondary rounded-t-2xl border-t border-separator/60 p-6 pb-safe overflow-y-auto max-h-[90vh]">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-headline font-semibold text-label-primary">{title}</h3>
          <button onClick={onClose} className="text-label-secondary active:opacity-60">
            <X className="h-5 w-5" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function FieldInput({
  label,
  value,
  onChange,
  placeholder,
  required,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  required?: boolean;
  type?: string;
}) {
  return (
    <div>
      <label className="text-caption-1 text-label-secondary mb-1 block">{label}</label>
      <input
        type={type}
        required={required}
        className="w-full rounded-xl bg-bg-elevated border border-separator/30 px-3 py-2 text-body text-label-primary"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

function FieldSelect({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="text-caption-1 text-label-secondary mb-1 block">{label}</label>
      <select
        className="w-full rounded-xl bg-bg-elevated border border-separator/30 px-3 py-2 text-body text-label-primary"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {children}
      </select>
    </div>
  );
}

function SubmitBtn({ loading, label }: { loading: boolean; label: string }) {
  return (
    <button
      type="submit"
      disabled={loading}
      className="w-full rounded-xl bg-accent text-white py-3 text-body font-semibold active:opacity-80 disabled:opacity-50"
    >
      {loading ? "Saving…" : label}
    </button>
  );
}

// ── Section header ────────────────────────────────────────────────────────────

function SectionHeader({ title, count, onAdd }: { title: string; count?: number; onAdd?: () => void }) {
  return (
    <div className="flex items-center justify-between px-4 pt-6 pb-2">
      <h2 className="text-headline font-semibold text-label-primary">{title}</h2>
      <div className="flex items-center gap-3">
        {count != null && (
          <span className="text-caption-1 text-label-tertiary">{count} item{count !== 1 ? "s" : ""}</span>
        )}
        {onAdd && (
          <button
            onClick={onAdd}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-accent/10 text-accent active:opacity-70"
          >
            <Plus className="h-4 w-4" strokeWidth={2.5} />
          </button>
        )}
      </div>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState({ label, onAdd }: { label: string; onAdd: () => void }) {
  return (
    <div className="px-4 py-12 text-center">
      <Shield className="mx-auto h-10 w-10 text-label-quaternary mb-3" strokeWidth={1} />
      <p className="text-body text-label-secondary">{label}</p>
      <button
        onClick={onAdd}
        className="mt-4 inline-flex items-center gap-1.5 rounded-xl bg-accent/10 text-accent px-4 py-2 text-callout font-medium active:opacity-70"
      >
        <Plus className="h-4 w-4" />
        Add
      </button>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

type Tab = "obligations" | "regulatory" | "insurance" | "checklists";

export default function CompliancePage() {
  const [tab, setTab] = React.useState<Tab>("obligations");
  const [modal, setModal] = React.useState<Tab | null>(null);

  const { data: summary, isLoading: summaryLoading } = useComplianceSummary();
  const { data: upcoming } = useComplianceUpcoming();
  const { data: obligations, isLoading: oblLoading } = useObligations();
  const { data: regulatory, isLoading: regLoading } = useRegulatoryItems();
  const { data: insurance, isLoading: insLoading } = useInsurancePolicies();
  const { data: checklists, isLoading: clLoading } = useChecklists();

  const tabs: { id: Tab; label: string; count?: number; alertCount?: number }[] = [
    { id: "obligations", label: "Obligations", count: obligations?.total ?? 0, alertCount: summary?.overdue_obligations },
    { id: "regulatory",  label: "Regulatory",  count: regulatory?.total ?? 0, alertCount: summary?.open_regulatory_items },
    { id: "insurance",   label: "Insurance",   count: insurance?.total ?? 0, alertCount: summary?.expiring_insurance_30d },
    { id: "checklists",  label: "Checklists",  count: checklists?.total ?? 0 },
  ];

  return (
    <MobileShell>
      <TopBar
        title="Compliance"
        right={
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-accent/10">
            <Shield className="h-4 w-4 text-accent" strokeWidth={1.75} />
          </span>
        }
      />

      {/* Summary cards */}
      <div className="px-4 pt-4">
        {summaryLoading ? (
          <div className="grid grid-cols-2 gap-3">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="rounded-2xl bg-bg-secondary border border-separator/30 h-20 animate-pulse" />
            ))}
          </div>
        ) : summary ? (
          <div className="grid grid-cols-2 gap-3">
            <SummaryCard
              label="Overdue Obligations"
              value={summary.overdue_obligations}
              color="red"
              alert={summary.overdue_obligations > 0}
              sub={summary.overdue_obligations > 0 ? "Needs attention" : "All current"}
            />
            <SummaryCard
              label="Expiring Insurance"
              value={summary.expiring_insurance_30d}
              color="orange"
              alert={summary.expiring_insurance_30d > 0}
              sub="Within 30 days"
            />
            <SummaryCard
              label="Open Regulatory"
              value={summary.open_regulatory_items}
              color="blue"
              sub="Open items"
            />
            <SummaryCard
              label="Checklist Complete"
              value={`${summary.checklists_complete_pct}%`}
              color={summary.checklists_complete_pct >= 80 ? "green" : "orange"}
              sub="Avg completion"
            />
          </div>
        ) : null}
      </div>

      {/* Upcoming deadlines */}
      {(summary?.upcoming_deadlines?.length ?? 0) > 0 && (
        <>
          <div className="flex items-center justify-between px-4 pt-6 pb-2">
            <h2 className="text-headline font-semibold text-label-primary">Upcoming Deadlines</h2>
            <span className="text-caption-1 text-label-tertiary">Next {summary!.upcoming_deadlines.length}</span>
          </div>
          <div className="mx-4 rounded-2xl bg-bg-secondary border border-separator/30 overflow-hidden">
            {summary!.upcoming_deadlines.map((d) => (
              <DeadlineRow key={`${d.deadline_type}-${d.id}`} item={d} />
            ))}
          </div>
        </>
      )}

      {/* Sprint 5.1 — Upcoming deadlines (30d): obligations + contract expirations */}
      {(upcoming?.items?.length ?? 0) > 0 && (
        <>
          <div className="flex items-center justify-between px-4 pt-6 pb-2">
            <h2 className="text-headline font-semibold text-label-primary">Upcoming Deadlines (30 Days)</h2>
            <span className="text-caption-1 text-label-tertiary">{upcoming!.items.length} due</span>
          </div>
          <div className="mx-4 rounded-2xl bg-bg-secondary border border-separator/30 overflow-hidden">
            {upcoming!.items.map((item) => (
              <div
                key={`${item.source}-${item.id}`}
                className="flex items-center justify-between gap-3 px-4 py-3 border-b border-separator/20 last:border-b-0"
              >
                <div className="min-w-0">
                  <p className="truncate text-body text-label-primary">{item.title}</p>
                  <p className="text-caption-1 text-label-tertiary">
                    <span className="uppercase">{item.source === "contract" ? "Contract" : "Obligation"}</span>
                    {item.due_date ? ` · due ${item.due_date}` : ""}
                  </p>
                </div>
                <span className="shrink-0 text-caption-1 text-label-secondary capitalize">{item.status}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Tabs */}
      <div className="mx-4 mt-6 flex gap-0.5 p-1 bg-bg-secondary rounded-xl border border-separator/30 overflow-x-auto">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "flex-1 min-w-0 py-2 px-3 rounded-lg text-caption-1 font-medium transition-colors whitespace-nowrap",
              tab === t.id
                ? "bg-accent text-white"
                : "text-label-secondary active:text-label-primary",
            )}
          >
            {t.label}
            {(t.alertCount ?? 0) > 0 && (
              <span className="ml-1 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-400 px-1 text-[10px] font-semibold text-white">
                {t.alertCount}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="pb-24">
        {tab === "obligations" && (
          <>
            <SectionHeader
              title="Contract Obligations"
              count={obligations?.total ?? 0}
              onAdd={() => setModal("obligations")}
            />
            {oblLoading ? (
              <div className="mx-4 space-y-2">
                {[0, 1, 2].map((i) => <div key={i} className="h-16 rounded-2xl bg-bg-secondary animate-pulse" />)}
              </div>
            ) : !obligations?.items.length ? (
              <EmptyState label="No obligations yet" onAdd={() => setModal("obligations")} />
            ) : (
              <div className="mx-4 rounded-2xl bg-bg-secondary border border-separator/30 overflow-hidden">
                {obligations.items.map((o) => <ObligationRow key={o.id} item={o} />)}
              </div>
            )}
          </>
        )}

        {tab === "regulatory" && (
          <>
            <SectionHeader
              title="Regulatory Filings"
              count={regulatory?.total ?? 0}
              onAdd={() => setModal("regulatory")}
            />
            {regLoading ? (
              <div className="mx-4 space-y-2">
                {[0, 1, 2].map((i) => <div key={i} className="h-16 rounded-2xl bg-bg-secondary animate-pulse" />)}
              </div>
            ) : !regulatory?.items.length ? (
              <EmptyState label="No regulatory items yet" onAdd={() => setModal("regulatory")} />
            ) : (
              <div className="mx-4 rounded-2xl bg-bg-secondary border border-separator/30 overflow-hidden">
                {regulatory.items.map((r) => <RegulatoryRow key={r.id} item={r} />)}
              </div>
            )}
          </>
        )}

        {tab === "insurance" && (
          <>
            <SectionHeader
              title="Insurance Policies"
              count={insurance?.total ?? 0}
              onAdd={() => setModal("insurance")}
            />
            {insLoading ? (
              <div className="mx-4 space-y-2">
                {[0, 1, 2].map((i) => <div key={i} className="h-16 rounded-2xl bg-bg-secondary animate-pulse" />)}
              </div>
            ) : !insurance?.items.length ? (
              <EmptyState label="No insurance policies yet" onAdd={() => setModal("insurance")} />
            ) : (
              <div className="mx-4 rounded-2xl bg-bg-secondary border border-separator/30 overflow-hidden">
                {insurance.items.map((p) => <InsuranceRow key={p.id} item={p} />)}
              </div>
            )}
          </>
        )}

        {tab === "checklists" && (
          <>
            <SectionHeader
              title="Compliance Checklists"
              count={checklists?.total ?? 0}
              onAdd={() => setModal("checklists")}
            />
            {clLoading ? (
              <div className="mx-4 space-y-2">
                {[0, 1, 2].map((i) => <div key={i} className="h-16 rounded-2xl bg-bg-secondary animate-pulse" />)}
              </div>
            ) : !checklists?.items.length ? (
              <EmptyState label="No checklists yet" onAdd={() => setModal("checklists")} />
            ) : (
              <div className="mx-4 rounded-2xl bg-bg-secondary border border-separator/30 overflow-hidden">
                {checklists.items.map((c) => <ChecklistCard key={c.id} item={c} />)}
              </div>
            )}
          </>
        )}
      </div>

      {/* Modals */}
      {modal === "obligations" && <NewObligationModal onClose={() => setModal(null)} />}
      {modal === "regulatory"  && <NewRegulatoryModal onClose={() => setModal(null)} />}
      {modal === "insurance"   && <NewInsuranceModal  onClose={() => setModal(null)} />}
      {modal === "checklists"  && <NewChecklistModal  onClose={() => setModal(null)} />}
    </MobileShell>
  );
}
