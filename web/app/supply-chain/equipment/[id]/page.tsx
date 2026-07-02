"use client";

/**
 * /supply-chain/equipment/[id] — Equipment Detail Page (Sprint 2B)
 *
 * Shows full procurement detail for a single equipment item.
 * Inline editing, status stepper, linked vendor card.
 * Design: dark Quill theme, iOS-style cards, accent blue #0A84FF.
 */

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  Box,
  CheckCircle2,
  Cpu,
  Factory,
  Link2,
  Package,
  Shield,
  Thermometer,
  Truck,
  Unplug,
  Wind,
  X,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { useEquipmentItem, useUpdateEquipment, useVendor } from "@/lib/api";
import type { Equipment } from "@/lib/schemas";
import { EQUIPMENT_CATEGORIES, EQUIPMENT_STATUSES } from "@/lib/schemas";

// ── Status stepper config ─────────────────────────────────────────────────────

const STATUS_STEPS = [
  { key: "not_ordered", label: "Not Ordered" },
  { key: "ordered",     label: "Ordered" },
  { key: "in_transit",  label: "In Transit" },
  { key: "received",    label: "Received" },
  { key: "installed",   label: "Installed" },
] as const;

// ── Category icon ─────────────────────────────────────────────────────────────

function CategoryIcon({ category, className }: { category: string; className?: string }) {
  const cls = cn("h-5 w-5", className);
  switch (category) {
    case "generator":  return <Zap className={cls} />;
    case "ups":        return <Unplug className={cls} />;
    case "switchgear": return <Cpu className={cls} />;
    case "cooling":    return <Thermometer className={cls} />;
    case "pdu":        return <Box className={cls} />;
    case "security":   return <Shield className={cls} />;
    case "fiber":      return <Wind className={cls} />;
    default:           return <Package className={cls} />;
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function fmtCurrency(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}K`;
  return `$${v.toFixed(0)}`;
}

// ── Inline editable field ─────────────────────────────────────────────────────

function EditableField({
  label,
  value,
  onSave,
  type = "text",
  options,
}: {
  label: string;
  value: string | null | undefined;
  onSave: (v: string) => Promise<void>;
  type?: "text" | "number" | "date" | "select" | "textarea";
  options?: string[];
}) {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(value ?? "");
  const [saving, setSaving] = React.useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      await onSave(draft);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => { setDraft(value ?? ""); setEditing(true); }}
        className="w-full text-left flex items-center justify-between gap-2 py-2 border-b border-separator/20 last:border-0 active:opacity-70 group"
      >
        <div>
          <p className="text-caption-2 text-label-tertiary">{label}</p>
          <p className="text-subhead text-label-primary mt-0.5">{value || "—"}</p>
        </div>
        <span className="text-caption-2 text-label-quaternary group-hover:text-label-secondary">Edit</span>
      </button>
    );
  }

  return (
    <div className="py-2 border-b border-separator/20 last:border-0">
      <p className="text-caption-2 text-label-tertiary mb-1">{label}</p>
      {type === "select" && options ? (
        <select
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          className="w-full rounded-xl bg-bg-elevated border border-accent/40 px-3 py-2 text-subhead text-label-primary focus:outline-none"
        >
          {options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      ) : type === "textarea" ? (
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={3}
          className="w-full rounded-xl bg-bg-elevated border border-accent/40 px-3 py-2 text-subhead text-label-primary focus:outline-none resize-none"
        />
      ) : (
        <input
          type={type}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          className="w-full rounded-xl bg-bg-elevated border border-accent/40 px-3 py-2 text-subhead text-label-primary focus:outline-none"
        />
      )}
      <div className="flex gap-2 mt-2">
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="flex-1 rounded-xl bg-accent py-2 text-caption-1 font-semibold text-white disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          onClick={() => setEditing(false)}
          className="flex-1 rounded-xl bg-bg-elevated py-2 text-caption-1 font-semibold text-label-secondary"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

// ── Status Stepper ────────────────────────────────────────────────────────────

function StatusStepper({
  currentStatus,
  onAdvance,
}: {
  currentStatus: string;
  onAdvance: (next: string) => Promise<void>;
}) {
  const [advancing, setAdvancing] = React.useState(false);
  const currentIdx = STATUS_STEPS.findIndex((s) => s.key === currentStatus);

  async function handleTap(idx: number) {
    if (idx <= currentIdx || advancing) return;
    if (idx !== currentIdx + 1) return; // only advance one step
    setAdvancing(true);
    try {
      await onAdvance(STATUS_STEPS[idx].key);
    } finally {
      setAdvancing(false);
    }
  }

  return (
    <div className="flex items-center gap-0 overflow-x-auto no-scrollbar px-1">
      {STATUS_STEPS.map((step, idx) => {
        const done = idx < currentIdx;
        const active = idx === currentIdx;
        const next = idx === currentIdx + 1;

        return (
          <React.Fragment key={step.key}>
            <button
              type="button"
              onClick={() => handleTap(idx)}
              disabled={!next || advancing}
              className={cn(
                "flex flex-col items-center gap-1 flex-none px-1",
                next ? "cursor-pointer opacity-100" : "cursor-default",
              )}
            >
              <div className={cn(
                "h-7 w-7 rounded-full border-2 flex items-center justify-center transition-colors",
                done   ? "bg-accent border-accent"         : "",
                active ? "bg-accent border-accent"         : "",
                next   ? "border-accent/50 bg-accent/10"  : "",
                !done && !active && !next ? "border-separator/40 bg-bg-elevated" : "",
              )}>
                {done ? (
                  <CheckCircle2 className="h-4 w-4 text-white" />
                ) : active ? (
                  <div className="h-2.5 w-2.5 rounded-full bg-white" />
                ) : (
                  <div className={cn(
                    "h-2.5 w-2.5 rounded-full",
                    next ? "bg-accent/50" : "bg-separator/40",
                  )} />
                )}
              </div>
              <span className={cn(
                "text-[10px] font-semibold whitespace-nowrap",
                active ? "text-accent" : done ? "text-label-secondary" : "text-label-quaternary",
              )}>
                {step.label}
              </span>
            </button>

            {/* Connector line */}
            {idx < STATUS_STEPS.length - 1 && (
              <div className={cn(
                "h-0.5 flex-1 min-w-[16px] rounded-full transition-colors",
                idx < currentIdx ? "bg-accent" : "bg-separator/30",
              )} />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}

// ── Linked Vendor Card ────────────────────────────────────────────────────────

function LinkedVendorCard({ vendorId, onLink }: { vendorId: string | null | undefined; onLink: () => void }) {
  const { data: vendor } = useVendor(vendorId);

  if (!vendorId || !vendor) {
    return (
      <button
        type="button"
        onClick={onLink}
        className="flex items-center gap-2 text-callout font-semibold text-accent active:opacity-70"
      >
        <Link2 className="h-4 w-4" />
        Link Vendor
      </button>
    );
  }

  return (
    <div className="rounded-2xl bg-bg-elevated border border-separator/40 px-4 py-4">
      <div className="flex items-center gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent/10 text-accent">
          <Factory className="h-4 w-4" />
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-subhead font-semibold text-label-primary truncate">{vendor.name}</p>
          <p className="text-caption-1 text-label-secondary capitalize">{vendor.category}</p>
        </div>
        {vendor.prequalified && (
          <span className="text-caption-2 font-semibold text-accent bg-accent/10 rounded-full px-1.5 py-0.5">
            Approved
          </span>
        )}
      </div>
      {(vendor.contact_name || vendor.contact_email || vendor.performance_score != null) && (
        <div className="mt-3 flex flex-col gap-1">
          {vendor.contact_name && (
            <p className="text-caption-1 text-label-secondary">{vendor.contact_name}</p>
          )}
          {vendor.contact_email && (
            <p className="text-caption-1 text-label-secondary">{vendor.contact_email}</p>
          )}
          {vendor.performance_score != null && (
            <p className="text-caption-1 text-label-secondary">
              Performance: <span className="text-label-primary font-semibold">{vendor.performance_score.toFixed(1)}/10</span>
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function EquipmentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: eq, isLoading, error } = useEquipmentItem(id);
  const updateEquipment = useUpdateEquipment(id);

  async function patch(updates: Partial<Equipment>) {
    await updateEquipment.mutateAsync(updates);
  }

  if (isLoading) {
    return (
      <MobileShell>
        <TopBar title="Equipment" icon={<Package className="h-5 w-5 text-accent" />} />
        <div className="flex items-center justify-center h-48">
          <p className="text-callout text-label-secondary">Loading…</p>
        </div>
      </MobileShell>
    );
  }

  if (!eq) {
    return (
      <MobileShell>
        <TopBar title="Equipment" icon={<Package className="h-5 w-5 text-accent" />} />
        <div className="flex items-center justify-center h-48">
          <p className="text-callout text-label-secondary">Equipment not found.</p>
        </div>
      </MobileShell>
    );
  }

  const totalCost = eq.unit_cost_usd != null ? eq.unit_cost_usd * eq.quantity : null;

  return (
    <MobileShell>
      <TopBar
        title={eq.name}
        icon={
          <button
            type="button"
            onClick={() => router.push("/supply-chain")}
            className="rounded-full p-1 -ml-1 hover:bg-bg-elevated active:bg-bg-elevated"
          >
            <ArrowLeft className="h-5 w-5 text-accent" />
          </button>
        }
      />

      <div className="px-4 flex flex-col gap-5 pb-10">

        {/* At-risk banner */}
        {eq.at_risk && (
          <div className="rounded-2xl bg-red-500/10 border border-red-500/30 px-4 py-3 flex items-start gap-2">
            <AlertTriangle className="h-4 w-4 text-red-400 mt-0.5 shrink-0" />
            <div>
              <p className="text-callout font-semibold text-red-400">Delivery at risk</p>
              <p className="text-caption-1 text-label-secondary mt-0.5">
                This item&apos;s delivery may threaten the construction schedule.
              </p>
            </div>
          </div>
        )}

        {/* Status stepper */}
        <div className="rounded-2xl bg-chrome border border-separator/40 px-4 py-4">
          <p className="text-footnote font-semibold text-label-secondary mb-3">PROCUREMENT STATUS</p>
          <StatusStepper
            currentStatus={eq.status}
            onAdvance={(next) => patch({ status: next })}
          />
          {eq.status === "cancelled" && (
            <p className="text-caption-1 text-red-400 mt-2 text-center">This item has been cancelled.</p>
          )}
        </div>

        {/* Identity card */}
        <div className="rounded-2xl bg-chrome border border-separator/40 px-4 py-4">
          <div className="flex items-center gap-3 mb-4">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent/10 text-accent">
              <CategoryIcon category={eq.category} />
            </span>
            <div>
              <p className="text-title-3 font-bold text-label-primary">{eq.name}</p>
              <p className="text-caption-1 text-label-secondary capitalize">{eq.category}</p>
            </div>
          </div>

          <EditableField
            label="Category"
            value={eq.category}
            type="select"
            options={[...EQUIPMENT_CATEGORIES]}
            onSave={(v) => patch({ category: v })}
          />
          <EditableField
            label="Manufacturer"
            value={eq.manufacturer}
            onSave={(v) => patch({ manufacturer: v || undefined })}
          />
          <EditableField
            label="Model Number"
            value={eq.model_number}
            onSave={(v) => patch({ model_number: v || undefined })}
          />
          <EditableField
            label="Quantity"
            value={String(eq.quantity)}
            type="number"
            onSave={(v) => patch({ quantity: parseInt(v) || 1 })}
          />
          <EditableField
            label="Project ID"
            value={eq.project_id}
            onSave={(v) => patch({ project_id: v || undefined })}
          />
        </div>

        {/* Cost + lead time card */}
        <div className="rounded-2xl bg-chrome border border-separator/40 px-4 py-4">
          <p className="text-footnote font-semibold text-label-secondary mb-3">COST & TIMELINE</p>

          <EditableField
            label="Unit Cost (USD)"
            value={eq.unit_cost_usd != null ? String(eq.unit_cost_usd) : ""}
            type="number"
            onSave={(v) => patch({ unit_cost_usd: v ? parseFloat(v) : undefined })}
          />

          {/* Computed total */}
          {totalCost != null && (
            <div className="py-2 border-b border-separator/20">
              <p className="text-caption-2 text-label-tertiary">Total Cost ({eq.quantity}×)</p>
              <p className="text-subhead font-bold text-label-primary mt-0.5">
                {totalCost >= 1_000_000
                  ? `$${(totalCost / 1_000_000).toFixed(2)}M`
                  : totalCost >= 1_000
                  ? `$${(totalCost / 1_000).toFixed(1)}K`
                  : `$${totalCost.toFixed(0)}`}
              </p>
            </div>
          )}

          <EditableField
            label="Lead Time (weeks)"
            value={eq.lead_time_weeks != null ? String(eq.lead_time_weeks) : ""}
            type="number"
            onSave={(v) => patch({ lead_time_weeks: v ? parseInt(v) : undefined })}
          />
          <EditableField
            label="Order Date"
            value={eq.order_date ?? ""}
            type="date"
            onSave={(v) => patch({ order_date: v || undefined })}
          />
          <EditableField
            label="Expected Delivery"
            value={eq.expected_delivery ?? ""}
            type="date"
            onSave={(v) => patch({ expected_delivery: v || undefined })}
          />
          <EditableField
            label="Actual Delivery"
            value={eq.actual_delivery ?? ""}
            type="date"
            onSave={(v) => patch({ actual_delivery: v || undefined })}
          />
        </div>

        {/* Notes */}
        <div className="rounded-2xl bg-chrome border border-separator/40 px-4 py-4">
          <p className="text-footnote font-semibold text-label-secondary mb-2">NOTES</p>
          <EditableField
            label="Notes"
            value={eq.notes}
            type="textarea"
            onSave={(v) => patch({ notes: v || undefined })}
          />
        </div>

        {/* Vendor */}
        <div className="rounded-2xl bg-chrome border border-separator/40 px-4 py-4">
          <p className="text-footnote font-semibold text-label-secondary mb-3">VENDOR</p>
          <LinkedVendorCard
            vendorId={eq.vendor_id}
            onLink={() => {
              // Show vendor ID edit field — in a full implementation,
              // this would open a vendor picker. For now, inline edit.
            }}
          />
          {/* Also allow manual edit of vendor_id */}
          <div className="mt-3">
            <EditableField
              label="Vendor ID (manual)"
              value={eq.vendor_id}
              onSave={(v) => patch({ vendor_id: v || undefined })}
            />
          </div>
        </div>

        {/* Cancel button for non-terminal statuses */}
        {!["cancelled", "installed", "received"].includes(eq.status) && (
          <button
            type="button"
            onClick={() => patch({ status: "cancelled" })}
            className="w-full rounded-xl border border-red-500/30 py-3 text-body font-semibold text-red-400 active:opacity-70"
          >
            Cancel This Item
          </button>
        )}
      </div>
    </MobileShell>
  );
}
