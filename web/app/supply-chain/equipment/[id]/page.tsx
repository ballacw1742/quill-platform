"use client";

/**
 * /supply-chain/equipment/[id] — Equipment Detail Page (Lovable UI port)
 *
 * Maps Lovable route supply-chain.$id → prod app/supply-chain/equipment/[id].
 * Visual layer ported from:
 *   quill-platform-builder/src/routes/supply-chain.$id.tsx
 * Data layer: prod @/lib/api hooks.
 */

import * as React from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
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
  Unplug,
  Wind,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { useEquipmentItem, useUpdateEquipment, useVendor } from "@/lib/api";
import type { Equipment } from "@/lib/schemas";
import { EQUIPMENT_CATEGORIES, type EquipmentStatus } from "@/lib/schemas";

// ── Status stepper config ─────────────────────────────────────────────────────

const STATUS_STEPS = [
  { key: "not_ordered", label: "Not Ordered" },
  { key: "ordered",     label: "Ordered" },
  { key: "in_transit",  label: "In Transit" },
  { key: "received",    label: "Received" },
  { key: "installed",   label: "Installed" },
] as const;

// ── Category icon ─────────────────────────────────────────────────────────────

function CategoryIcon({
  category,
  className,
}: {
  category: string;
  className?: string;
}) {
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
  options?: readonly string[];
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
        onClick={() => {
          setDraft(value ?? "");
          setEditing(true);
        }}
        className="w-full text-left flex items-center justify-between gap-2 py-2 border-b border-hairline last:border-0 active:opacity-70 group"
      >
        <div>
          <p className="text-caption-2 text-label-tertiary">{label}</p>
          <p className="text-subhead text-label-primary mt-0.5">
            {value || "—"}
          </p>
        </div>
        <span className="text-caption-2 text-label-tertiary group-hover:text-label-secondary">
          Edit
        </span>
      </button>
    );
  }

  const inputCls =
    "w-full rounded-xl bg-bg-elevated border border-accent/40 px-3 py-2 text-subhead text-label-primary focus:outline-none";

  return (
    <div className="py-2 border-b border-hairline last:border-0">
      <p className="text-caption-2 text-label-tertiary mb-1">{label}</p>
      {type === "select" && options ? (
        <select
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          className={inputCls}
        >
          {options.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      ) : type === "textarea" ? (
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={3}
          className={cn(inputCls, "resize-none")}
        />
      ) : (
        <input
          type={type}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          className={inputCls}
        />
      )}
      <div className="flex gap-2 mt-2">
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="flex-1 rounded-full bg-accent py-2 text-caption-1 font-semibold text-primary-foreground shadow-card active:scale-[0.98] transition-all disabled:opacity-50"
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

// ── Status stepper ────────────────────────────────────────────────────────────

function StatusStepper({
  currentStatus,
  onAdvance,
}: {
  currentStatus: string;
  onAdvance: (next: EquipmentStatus) => Promise<void>;
}) {
  const [advancing, setAdvancing] = React.useState(false);
  const currentIdx = STATUS_STEPS.findIndex((s) => s.key === currentStatus);

  async function handleTap(idx: number) {
    if (idx <= currentIdx || advancing) return;
    if (idx !== currentIdx + 1) return;
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
              <div
                className={cn(
                  "h-7 w-7 rounded-full border-2 flex items-center justify-center transition-colors",
                  done && "bg-accent border-accent",
                  active && "bg-accent border-accent",
                  next && "border-accent/50 bg-accent/10",
                  !done && !active && !next && "border-hairline bg-bg-elevated",
                )}
              >
                {done ? (
                  <CheckCircle2 className="h-4 w-4 text-primary-foreground" />
                ) : active ? (
                  <div className="h-2.5 w-2.5 rounded-full bg-primary-foreground" />
                ) : (
                  <div
                    className={cn(
                      "h-2.5 w-2.5 rounded-full",
                      next ? "bg-accent/50" : "bg-separator",
                    )}
                  />
                )}
              </div>
              <span
                className={cn(
                  "text-caption-2 font-semibold whitespace-nowrap",
                  active
                    ? "text-accent"
                    : done
                      ? "text-label-secondary"
                      : "text-label-tertiary",
                )}
              >
                {step.label}
              </span>
            </button>
            {idx < STATUS_STEPS.length - 1 && (
              <div
                className={cn(
                  "h-0.5 flex-1 min-w-[16px] rounded-full transition-colors",
                  idx < currentIdx ? "bg-accent" : "bg-separator",
                )}
              />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}

// ── Linked vendor card ────────────────────────────────────────────────────────

function LinkedVendorCard({ vendorId }: { vendorId: string | null | undefined }) {
  const { data: vendor } = useVendor(vendorId);

  if (!vendorId || !vendor) {
    return (
      <div className="flex items-center gap-2 text-callout text-label-secondary">
        <Link2 className="h-4 w-4" />
        No vendor linked
      </div>
    );
  }

  return (
    <div className="rounded-2xl bg-bg-elevated border border-hairline px-4 py-4">
      <div className="flex items-center gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent/10 text-accent hover:bg-accent/20 active:scale-[0.98] transition-all">
          <Factory className="h-4 w-4" />
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-subhead font-semibold text-label-primary truncate">
            {vendor.name}
          </p>
          <p className="text-caption-1 text-label-secondary capitalize">
            {vendor.category}
          </p>
        </div>
        {vendor.prequalified && (
          <span className="text-caption-2 font-semibold text-accent bg-accent/10 rounded-full px-1.5 py-0.5">
            Approved
          </span>
        )}
      </div>
      {(vendor.contact_name ||
        vendor.contact_email ||
        vendor.performance_score != null) && (
        <div className="mt-3 flex flex-col gap-1">
          {vendor.contact_name && (
            <p className="text-caption-1 text-label-secondary">
              {vendor.contact_name}
            </p>
          )}
          {vendor.contact_email && (
            <p className="text-caption-1 text-label-secondary">
              {vendor.contact_email}
            </p>
          )}
          {vendor.performance_score != null && (
            <p className="text-caption-1 text-label-secondary">
              Performance:{" "}
              <span className="text-label-primary font-semibold">
                {vendor.performance_score.toFixed(1)}/10
              </span>
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function EquipmentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: eq, isLoading } = useEquipmentItem(id);
  const updateEquipment = useUpdateEquipment(id);

  async function patch(updates: Partial<Equipment>) {
    await updateEquipment.mutateAsync(updates);
  }

  const backButton = (
    <Link
      href="/supply-chain"
      aria-label="Back to Supply Chain"
      className="-ml-2 flex min-h-[44px] min-w-[44px] max-w-full items-center gap-1 rounded-md px-2 text-accent active:opacity-60 no-tap-highlight"
    >
      <svg
        viewBox="0 0 12 22"
        className="h-[18px] w-[10px]"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <polyline points="11,2 2,11 11,20" />
      </svg>
      <span className="text-body truncate">Supply Chain</span>
    </Link>
  );

  if (isLoading) {
    return (
      <MobileShell>
        <TopBar title="Equipment" left={backButton} />
        <div className="flex items-center justify-center h-48">
          <p className="text-callout text-label-secondary">Loading…</p>
        </div>
      </MobileShell>
    );
  }

  if (!eq) {
    return (
      <MobileShell>
        <TopBar title="Equipment" left={backButton} />
        <div className="flex items-center justify-center h-48">
          <p className="text-callout text-label-secondary">
            Equipment not found.
          </p>
        </div>
      </MobileShell>
    );
  }

  const totalCost =
    eq.unit_cost_usd != null ? eq.unit_cost_usd * eq.quantity : null;

  return (
    <MobileShell>
      <TopBar title={eq.name} left={backButton} />

      <div className="px-4 flex flex-col gap-5 pb-10">
        {/* At-risk banner */}
        {eq.at_risk && (
          <div className="rounded-2xl bg-danger/10 border border-danger/30 px-4 py-3 flex items-start gap-2">
            <AlertTriangle className="h-4 w-4 text-danger mt-0.5 shrink-0" />
            <div>
              <p className="text-callout font-semibold text-danger">
                Delivery at risk
              </p>
              <p className="text-caption-1 text-label-secondary mt-0.5">
                This item&apos;s delivery may threaten the construction schedule.
              </p>
            </div>
          </div>
        )}

        {/* Status stepper */}
        <div className="rounded-2xl bg-chrome border border-hairline px-4 py-4">
          <p className="text-footnote font-semibold text-label-secondary mb-3">
            PROCUREMENT STATUS
          </p>
          <StatusStepper
            currentStatus={eq.status}
            onAdvance={(next) => patch({ status: next })}
          />
          {eq.status === "cancelled" && (
            <p className="text-caption-1 text-danger mt-2 text-center">
              This item has been cancelled.
            </p>
          )}
        </div>

        {/* Identity card */}
        <div className="rounded-2xl bg-chrome border border-hairline px-4 py-4">
          <div className="flex items-center gap-3 mb-4">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent/10 text-accent hover:bg-accent/20 active:scale-[0.98] transition-all">
              <CategoryIcon category={eq.category} />
            </span>
            <div>
              <p className="text-title-3 font-bold text-label-primary">
                {eq.name}
              </p>
              <p className="text-caption-1 text-label-secondary capitalize">
                {eq.category}
              </p>
            </div>
          </div>

          <EditableField
            label="Category"
            value={eq.category}
            type="select"
            options={EQUIPMENT_CATEGORIES}
            onSave={(v) => patch({ category: v })}
          />
          <EditableField
            label="Manufacturer"
            value={eq.manufacturer}
            onSave={(v) => patch({ manufacturer: v || null })}
          />
          <EditableField
            label="Model Number"
            value={eq.model_number}
            onSave={(v) => patch({ model_number: v || null })}
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
            onSave={(v) => patch({ project_id: v || null })}
          />
        </div>

        {/* Cost + timeline card */}
        <div className="rounded-2xl bg-chrome border border-hairline px-4 py-4">
          <p className="text-footnote font-semibold text-label-secondary mb-3">
            COST &amp; TIMELINE
          </p>

          <EditableField
            label="Unit Cost (USD)"
            value={eq.unit_cost_usd != null ? String(eq.unit_cost_usd) : ""}
            type="number"
            onSave={(v) =>
              patch({ unit_cost_usd: v ? parseFloat(v) : null })
            }
          />

          {totalCost != null && (
            <div className="py-2 border-b border-hairline">
              <p className="text-caption-2 text-label-tertiary">
                Total Cost ({eq.quantity}×)
              </p>
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
            onSave={(v) =>
              patch({ lead_time_weeks: v ? parseInt(v) : null })
            }
          />
          <EditableField
            label="Order Date"
            value={eq.order_date ?? ""}
            type="date"
            onSave={(v) => patch({ order_date: v || null })}
          />
          <EditableField
            label="Expected Delivery"
            value={eq.expected_delivery ?? ""}
            type="date"
            onSave={(v) => patch({ expected_delivery: v || null })}
          />
          <EditableField
            label="Actual Delivery"
            value={eq.actual_delivery ?? ""}
            type="date"
            onSave={(v) => patch({ actual_delivery: v || null })}
          />
        </div>

        {/* Notes */}
        <div className="rounded-2xl bg-chrome border border-hairline px-4 py-4">
          <p className="text-footnote font-semibold text-label-secondary mb-2">
            NOTES
          </p>
          <EditableField
            label="Notes"
            value={eq.notes}
            type="textarea"
            onSave={(v) => patch({ notes: v || null })}
          />
        </div>

        {/* Vendor */}
        <div className="rounded-2xl bg-chrome border border-hairline px-4 py-4">
          <p className="text-footnote font-semibold text-label-secondary mb-3">
            VENDOR
          </p>
          <LinkedVendorCard vendorId={eq.vendor_id} />
          <div className="mt-3">
            <EditableField
              label="Vendor ID (manual)"
              value={eq.vendor_id}
              onSave={(v) => patch({ vendor_id: v || null })}
            />
          </div>
        </div>

        {/* Cancel button for non-terminal statuses */}
        {!(["cancelled", "installed", "received"] as EquipmentStatus[]).includes(
          eq.status as EquipmentStatus,
        ) && (
          <button
            type="button"
            onClick={() => patch({ status: "cancelled" })}
            className="w-full rounded-xl border border-danger/30 py-3 text-body font-semibold text-danger active:opacity-70"
          >
            Cancel This Item
          </button>
        )}
      </div>
    </MobileShell>
  );
}
