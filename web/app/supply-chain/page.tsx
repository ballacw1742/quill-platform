"use client";

/**
 * /supply-chain — Supply Chain module (Sprint 2B)
 *
 * Tracks equipment procurement for construction projects and vendor relationships.
 * Surfaces long-lead item risks (generators, switchgear with 40–52 week lead times)
 * before they blow the construction schedule.
 *
 * Design: dark Quill chrome, accent blue #0A84FF, matches /pipeline and /operations.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  Box,
  Building2,
  ChevronRight,
  Cpu,
  Factory,
  Package,
  Plus,
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
import {
  useEquipment,
  useVendors,
  useSupplyChainSummary,
  useAtRiskEquipment,
  useCreateEquipment,
  useCreateVendor,
} from "@/lib/api";
import type { Equipment, Vendor, SupplyChainSummary } from "@/lib/schemas";
import {
  EQUIPMENT_CATEGORIES,
  EQUIPMENT_STATUSES,
  VENDOR_CATEGORIES,
} from "@/lib/schemas";

// ── Category icons ────────────────────────────────────────────────────────────

function CategoryIcon({ category, className }: { category: string; className?: string }) {
  const cls = cn("h-4 w-4", className);
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

// ── Status badge ──────────────────────────────────────────────────────────────

function statusBadge(s: string): { label: string; cls: string } {
  switch (s) {
    case "not_ordered": return { label: "Not Ordered",  cls: "text-zinc-400 bg-zinc-400/10" };
    case "ordered":     return { label: "Ordered",      cls: "text-blue-400 bg-blue-400/10" };
    case "in_transit":  return { label: "In Transit",   cls: "text-yellow-400 bg-yellow-400/10" };
    case "received":    return { label: "Received",     cls: "text-green-400 bg-green-400/10" };
    case "installed":   return { label: "Installed",    cls: "text-teal-400 bg-teal-400/10" };
    case "cancelled":   return { label: "Cancelled",    cls: "text-zinc-500 bg-zinc-500/10" };
    default:            return { label: s,              cls: "text-label-secondary bg-bg-elevated" };
  }
}

function fmtDate(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function fmtValue(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
  return `$${v.toFixed(0)}`;
}

// ── Summary bar ───────────────────────────────────────────────────────────────

function SummaryBar({ summary }: { summary: SupplyChainSummary }) {
  const stats = [
    { label: "Equipment Items", value: String(summary.total_equipment_items) },
    {
      label: "Total Value",
      value: summary.total_equipment_value_usd > 0
        ? `$${(summary.total_equipment_value_usd / 1_000_000).toFixed(1)}M`
        : "—",
    },
    {
      label: "At Risk",
      value: String(summary.at_risk_count),
      urgent: summary.at_risk_count > 0,
    },
    { label: "Approved Vendors", value: String(summary.approved_vendor_count) },
  ];

  return (
    <div className="flex gap-3 px-4 mb-4 overflow-x-auto no-scrollbar">
      {stats.map((s) => (
        <div
          key={s.label}
          className={cn(
            "flex-none rounded-2xl px-4 py-3 text-center",
            "bg-chrome/80 border border-separator/40",
            "min-w-[100px]",
          )}
        >
          <p className={cn(
            "text-title-3 font-bold tabular-nums",
            s.urgent ? "text-red-400" : "text-label-primary",
          )}>
            {s.value}
          </p>
          <p className="text-caption-2 text-label-secondary mt-0.5">{s.label}</p>
        </div>
      ))}
    </div>
  );
}

// ── Equipment row ─────────────────────────────────────────────────────────────

function EquipmentRow({ eq, onClick }: { eq: Equipment; onClick: () => void }) {
  const badge = statusBadge(eq.status);

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full text-left flex items-center gap-3 px-4 py-3",
        "border-b border-separator/30 last:border-0",
        "active:bg-bg-elevated/50 transition-colors no-tap-highlight",
      )}
    >
      {/* Category icon */}
      <span className={cn(
        "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl",
        eq.at_risk ? "bg-red-500/15 text-red-400" : "bg-accent/10 text-accent",
      )}>
        <CategoryIcon category={eq.category} />
      </span>

      {/* Main content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-subhead font-semibold text-label-primary truncate">{eq.name}</span>
          {eq.at_risk && (
            <AlertTriangle className="h-3 w-3 text-red-400 shrink-0" />
          )}
        </div>
        <p className="text-caption-1 text-label-secondary truncate">
          {eq.project_id ? `Project ${eq.project_id.slice(0, 8)}…` : "No project"}{" "}
          {eq.vendor_id ? "· Vendor linked" : ""}
        </p>
      </div>

      {/* Right side */}
      <div className="flex flex-col items-end gap-1 shrink-0">
        <span className={cn("rounded-full px-2 py-0.5 text-caption-2 font-semibold", badge.cls)}>
          {badge.label}
        </span>
        {eq.expected_delivery && (
          <span className={cn(
            "text-caption-2",
            eq.at_risk ? "text-red-400 font-semibold" : "text-label-tertiary",
          )}>
            {fmtDate(eq.expected_delivery)}
          </span>
        )}
      </div>

      <ChevronRight className="h-4 w-4 text-label-quaternary shrink-0" />
    </button>
  );
}

// ── Vendor card ───────────────────────────────────────────────────────────────

function VendorCard({ vendor }: { vendor: Vendor }) {
  return (
    <div className={cn(
      "rounded-2xl bg-bg-elevated border border-separator/40 px-4 py-4",
      "flex flex-col gap-2",
    )}>
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-accent/10 text-accent">
            <Factory className="h-4 w-4" />
          </span>
          <span className="text-subhead font-semibold text-label-primary truncate">
            {vendor.name}
          </span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <span className="text-caption-2 font-semibold text-blue-400 bg-blue-400/10 rounded-full px-1.5 py-0.5 capitalize">
            {vendor.category}
          </span>
          {vendor.prequalified && (
            <span className="text-caption-2 font-semibold text-accent bg-accent/10 rounded-full px-1.5 py-0.5">
              Approved
            </span>
          )}
        </div>
      </div>

      {/* Stats row */}
      <div className="flex items-center gap-3 flex-wrap">
        {vendor.performance_score != null && (
          <span className="text-caption-1 text-label-secondary">
            Score: <span className="text-label-primary font-semibold">{vendor.performance_score.toFixed(1)}/10</span>
          </span>
        )}
        {vendor.contact_name && (
          <span className="text-caption-1 text-label-secondary truncate">
            {vendor.contact_name}
          </span>
        )}
        {vendor.contact_email && (
          <span className="text-caption-1 text-label-secondary truncate">
            {vendor.contact_email}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Add Equipment Modal ───────────────────────────────────────────────────────

function AddEquipmentModal({ onClose }: { onClose: () => void }) {
  const createEquipment = useCreateEquipment();
  const [form, setForm] = React.useState({
    name: "",
    category: "generator",
    project_id: "",
    quantity: "1",
    unit_cost_usd: "",
    lead_time_weeks: "",
    order_date: "",
    expected_delivery: "",
    vendor_id: "",
    status: "not_ordered",
    notes: "",
  });

  const set = (k: string, v: string) => setForm((f) => ({ ...f, [k]: v }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    await createEquipment.mutateAsync({
      name: form.name,
      category: form.category,
      project_id: form.project_id || undefined,
      quantity: parseInt(form.quantity) || 1,
      unit_cost_usd: form.unit_cost_usd ? parseFloat(form.unit_cost_usd) : undefined,
      lead_time_weeks: form.lead_time_weeks ? parseInt(form.lead_time_weeks) : undefined,
      order_date: form.order_date || undefined,
      expected_delivery: form.expected_delivery || undefined,
      vendor_id: form.vendor_id || undefined,
      status: form.status,
      notes: form.notes || undefined,
    } as Partial<Equipment>);
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg rounded-t-3xl bg-chrome border-t border-separator/40 pb-safe-or-6 overflow-y-auto max-h-[90vh]">
        {/* Header */}
        <div className="sticky top-0 flex items-center justify-between px-4 py-4 bg-chrome border-b border-separator/30">
          <h2 className="text-title-3 font-bold text-label-primary">Add Equipment</h2>
          <button type="button" onClick={onClose} className="rounded-full p-1.5 hover:bg-bg-elevated active:bg-bg-elevated">
            <X className="h-5 w-5 text-label-secondary" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4 px-4 py-4">
          {/* Name */}
          <div>
            <label className="text-footnote font-semibold text-label-secondary block mb-1">Name *</label>
            <input
              required
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              placeholder="e.g. 2MW Caterpillar Generator"
              className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2 text-body text-label-primary placeholder:text-label-quaternary focus:outline-none focus:border-accent"
            />
          </div>

          {/* Category + Status */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-footnote font-semibold text-label-secondary block mb-1">Category</label>
              <select
                value={form.category}
                onChange={(e) => set("category", e.target.value)}
                className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2 text-body text-label-primary focus:outline-none focus:border-accent"
              >
                {EQUIPMENT_CATEGORIES.map((c) => (
                  <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-footnote font-semibold text-label-secondary block mb-1">Status</label>
              <select
                value={form.status}
                onChange={(e) => set("status", e.target.value)}
                className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2 text-body text-label-primary focus:outline-none focus:border-accent"
              >
                {EQUIPMENT_STATUSES.map((s) => (
                  <option key={s} value={s}>{s.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase())}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Project ID + Quantity */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-footnote font-semibold text-label-secondary block mb-1">Project ID</label>
              <input
                value={form.project_id}
                onChange={(e) => set("project_id", e.target.value)}
                placeholder="UUID"
                className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2 text-body text-label-primary placeholder:text-label-quaternary focus:outline-none focus:border-accent"
              />
            </div>
            <div>
              <label className="text-footnote font-semibold text-label-secondary block mb-1">Quantity</label>
              <input
                type="number"
                min="1"
                value={form.quantity}
                onChange={(e) => set("quantity", e.target.value)}
                className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2 text-body text-label-primary focus:outline-none focus:border-accent"
              />
            </div>
          </div>

          {/* Unit Cost + Lead Time */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-footnote font-semibold text-label-secondary block mb-1">Unit Cost (USD)</label>
              <input
                type="number"
                min="0"
                step="0.01"
                value={form.unit_cost_usd}
                onChange={(e) => set("unit_cost_usd", e.target.value)}
                placeholder="0.00"
                className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2 text-body text-label-primary placeholder:text-label-quaternary focus:outline-none focus:border-accent"
              />
            </div>
            <div>
              <label className="text-footnote font-semibold text-label-secondary block mb-1">Lead Time (weeks)</label>
              <input
                type="number"
                min="0"
                value={form.lead_time_weeks}
                onChange={(e) => set("lead_time_weeks", e.target.value)}
                placeholder="52"
                className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2 text-body text-label-primary placeholder:text-label-quaternary focus:outline-none focus:border-accent"
              />
            </div>
          </div>

          {/* Order Date + Expected Delivery */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-footnote font-semibold text-label-secondary block mb-1">Order Date</label>
              <input
                type="date"
                value={form.order_date}
                onChange={(e) => set("order_date", e.target.value)}
                className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2 text-body text-label-primary focus:outline-none focus:border-accent"
              />
            </div>
            <div>
              <label className="text-footnote font-semibold text-label-secondary block mb-1">Expected Delivery</label>
              <input
                type="date"
                value={form.expected_delivery}
                onChange={(e) => set("expected_delivery", e.target.value)}
                className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2 text-body text-label-primary focus:outline-none focus:border-accent"
              />
            </div>
          </div>

          {/* Vendor ID */}
          <div>
            <label className="text-footnote font-semibold text-label-secondary block mb-1">Vendor ID</label>
            <input
              value={form.vendor_id}
              onChange={(e) => set("vendor_id", e.target.value)}
              placeholder="Vendor UUID"
              className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2 text-body text-label-primary placeholder:text-label-quaternary focus:outline-none focus:border-accent"
            />
          </div>

          {/* Notes */}
          <div>
            <label className="text-footnote font-semibold text-label-secondary block mb-1">Notes</label>
            <textarea
              value={form.notes}
              onChange={(e) => set("notes", e.target.value)}
              rows={3}
              placeholder="Any additional notes..."
              className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2 text-body text-label-primary placeholder:text-label-quaternary focus:outline-none focus:border-accent resize-none"
            />
          </div>

          {createEquipment.error && (
            <p className="text-caption-1 text-red-400">{createEquipment.error.message}</p>
          )}

          <button
            type="submit"
            disabled={createEquipment.isPending || !form.name}
            className="w-full rounded-xl bg-accent py-3 text-body font-semibold text-white disabled:opacity-50 active:opacity-80"
          >
            {createEquipment.isPending ? "Adding…" : "Add Equipment"}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── Add Vendor Modal ──────────────────────────────────────────────────────────

function AddVendorModal({ onClose }: { onClose: () => void }) {
  const createVendor = useCreateVendor();
  const [form, setForm] = React.useState({
    name: "",
    category: "generator",
    contact_name: "",
    contact_email: "",
    contact_phone: "",
    website: "",
    prequalified: false,
    performance_score: "",
    notes: "",
  });

  const set = (k: string, v: string | boolean) =>
    setForm((f) => ({ ...f, [k]: v }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    await createVendor.mutateAsync({
      name: form.name,
      category: form.category,
      contact_name: form.contact_name || undefined,
      contact_email: form.contact_email || undefined,
      contact_phone: form.contact_phone || undefined,
      website: form.website || undefined,
      prequalified: form.prequalified,
      performance_score: form.performance_score
        ? parseFloat(form.performance_score)
        : undefined,
      notes: form.notes || undefined,
    } as Partial<Vendor>);
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg rounded-t-3xl bg-chrome border-t border-separator/40 pb-safe-or-6 overflow-y-auto max-h-[90vh]">
        <div className="sticky top-0 flex items-center justify-between px-4 py-4 bg-chrome border-b border-separator/30">
          <h2 className="text-title-3 font-bold text-label-primary">Add Vendor</h2>
          <button type="button" onClick={onClose} className="rounded-full p-1.5 hover:bg-bg-elevated active:bg-bg-elevated">
            <X className="h-5 w-5 text-label-secondary" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4 px-4 py-4">
          {/* Name + Category */}
          <div>
            <label className="text-footnote font-semibold text-label-secondary block mb-1">Vendor Name *</label>
            <input
              required
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              placeholder="e.g. Cummins Power Systems"
              className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2 text-body text-label-primary placeholder:text-label-quaternary focus:outline-none focus:border-accent"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-footnote font-semibold text-label-secondary block mb-1">Category</label>
              <select
                value={form.category}
                onChange={(e) => set("category", e.target.value)}
                className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2 text-body text-label-primary focus:outline-none focus:border-accent"
              >
                {VENDOR_CATEGORIES.map((c) => (
                  <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-footnote font-semibold text-label-secondary block mb-1">Performance Score</label>
              <input
                type="number"
                min="0"
                max="10"
                step="0.1"
                value={form.performance_score}
                onChange={(e) => set("performance_score", e.target.value)}
                placeholder="0–10"
                className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2 text-body text-label-primary placeholder:text-label-quaternary focus:outline-none focus:border-accent"
              />
            </div>
          </div>

          {/* Contact */}
          <div>
            <label className="text-footnote font-semibold text-label-secondary block mb-1">Contact Name</label>
            <input
              value={form.contact_name}
              onChange={(e) => set("contact_name", e.target.value)}
              placeholder="Full name"
              className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2 text-body text-label-primary placeholder:text-label-quaternary focus:outline-none focus:border-accent"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-footnote font-semibold text-label-secondary block mb-1">Email</label>
              <input
                type="email"
                value={form.contact_email}
                onChange={(e) => set("contact_email", e.target.value)}
                placeholder="vendor@example.com"
                className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2 text-body text-label-primary placeholder:text-label-quaternary focus:outline-none focus:border-accent"
              />
            </div>
            <div>
              <label className="text-footnote font-semibold text-label-secondary block mb-1">Phone</label>
              <input
                value={form.contact_phone}
                onChange={(e) => set("contact_phone", e.target.value)}
                placeholder="+1 (555) 000-0000"
                className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2 text-body text-label-primary placeholder:text-label-quaternary focus:outline-none focus:border-accent"
              />
            </div>
          </div>

          {/* Website + Prequalified */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-footnote font-semibold text-label-secondary block mb-1">Website</label>
              <input
                value={form.website}
                onChange={(e) => set("website", e.target.value)}
                placeholder="https://..."
                className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2 text-body text-label-primary placeholder:text-label-quaternary focus:outline-none focus:border-accent"
              />
            </div>
            <div className="flex items-end pb-2">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.prequalified}
                  onChange={(e) => set("prequalified", e.target.checked)}
                  className="h-4 w-4 rounded accent-accent"
                />
                <span className="text-body text-label-primary">Pre-qualified</span>
              </label>
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="text-footnote font-semibold text-label-secondary block mb-1">Notes</label>
            <textarea
              value={form.notes}
              onChange={(e) => set("notes", e.target.value)}
              rows={2}
              placeholder="Any additional notes..."
              className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2 text-body text-label-primary placeholder:text-label-quaternary focus:outline-none focus:border-accent resize-none"
            />
          </div>

          {createVendor.error && (
            <p className="text-caption-1 text-red-400">{createVendor.error.message}</p>
          )}

          <button
            type="submit"
            disabled={createVendor.isPending || !form.name}
            className="w-full rounded-xl bg-accent py-3 text-body font-semibold text-white disabled:opacity-50 active:opacity-80"
          >
            {createVendor.isPending ? "Adding…" : "Add Vendor"}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── Filter tabs ───────────────────────────────────────────────────────────────

type EquipmentFilter = "all" | "at_risk" | string; // string for status filters

// ── Main page ─────────────────────────────────────────────────────────────────

export default function SupplyChainPage() {
  const router = useRouter();
  const [activeTab, setActiveTab] = React.useState<"equipment" | "vendors">("equipment");
  const [eqFilter, setEqFilter] = React.useState<EquipmentFilter>("all");
  const [showAddEquipment, setShowAddEquipment] = React.useState(false);
  const [showAddVendor, setShowAddVendor] = React.useState(false);

  const { data: summary } = useSupplyChainSummary();
  const { data: atRiskData } = useAtRiskEquipment();
  const atRisk = atRiskData?.items ?? [];

  const { data: equipData, isLoading: eqLoading } = useEquipment(
    null,
    eqFilter !== "all" && eqFilter !== "at_risk" ? eqFilter : null,
    eqFilter === "at_risk" ? true : null,
  );
  const equipItems = equipData?.items ?? [];

  const { data: vendorData, isLoading: vendorLoading } = useVendors();
  const vendors = vendorData?.items ?? [];

  return (
    <MobileShell>
      <TopBar
        title="Supply Chain"
        icon={<Package className="h-5 w-5 text-accent" />}
      />

      {/* Summary bar */}
      {summary && <SummaryBar summary={summary} />}

      {/* Tab toggle */}
      <div className="flex items-center gap-2 px-4 mb-4">
        {(["equipment", "vendors"] as const).map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className={cn(
              "flex-1 rounded-xl py-2 text-callout font-semibold transition-colors",
              activeTab === tab
                ? "bg-accent text-white"
                : "bg-bg-elevated text-label-secondary",
            )}
          >
            {tab === "equipment" ? "Equipment" : "Vendor Registry"}
          </button>
        ))}
      </div>

      {activeTab === "equipment" && (
        <>
          {/* At-risk alert banner */}
          {atRisk.length > 0 && eqFilter !== "at_risk" && (
            <div className="mx-4 mb-4 rounded-2xl bg-yellow-500/10 border border-yellow-500/30 px-4 py-3">
              <div className="flex items-start gap-2">
                <AlertTriangle className="h-4 w-4 text-yellow-400 mt-0.5 shrink-0" />
                <div className="flex-1">
                  <p className="text-callout font-semibold text-yellow-400">
                    {atRisk.length} item{atRisk.length !== 1 ? "s" : ""} at delivery risk
                  </p>
                  <p className="text-caption-1 text-label-secondary mt-0.5">
                    These items may threaten your construction schedule.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setEqFilter("at_risk")}
                  className="text-caption-1 font-semibold text-yellow-400 hover:text-yellow-300 shrink-0"
                >
                  View
                </button>
              </div>
            </div>
          )}

          {/* Equipment filter pills */}
          <div className="flex gap-2 px-4 mb-3 overflow-x-auto no-scrollbar">
            {[
              { key: "all",       label: "All" },
              { key: "at_risk",   label: "⚠ At Risk" },
              { key: "not_ordered", label: "Not Ordered" },
              { key: "ordered",   label: "Ordered" },
              { key: "in_transit", label: "In Transit" },
              { key: "received",  label: "Received" },
              { key: "installed", label: "Installed" },
            ].map(({ key, label }) => (
              <button
                key={key}
                type="button"
                onClick={() => setEqFilter(key as EquipmentFilter)}
                className={cn(
                  "flex-none rounded-full px-3 py-1 text-caption-1 font-semibold transition-colors",
                  eqFilter === key
                    ? "bg-accent text-white"
                    : "bg-bg-elevated text-label-secondary",
                )}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Equipment list */}
          <div className="mx-4 rounded-2xl bg-chrome border border-separator/40 overflow-hidden mb-6">
            {eqLoading ? (
              <p className="py-8 text-center text-callout text-label-secondary">Loading…</p>
            ) : equipItems.length === 0 ? (
              <p className="py-8 text-center text-callout text-label-secondary">
                {eqFilter === "at_risk"
                  ? "No at-risk items. Schedule is safe! ✅"
                  : "No equipment items yet. Use the + button to add one."}
              </p>
            ) : (
              equipItems.map((eq) => (
                <EquipmentRow
                  key={eq.id}
                  eq={eq}
                  onClick={() => router.push(`/supply-chain/equipment/${eq.id}`)}
                />
              ))
            )}
          </div>
        </>
      )}

      {activeTab === "vendors" && (
        <div className="px-4 flex flex-col gap-3 mb-6">
          {/* Add Vendor button */}
          <div className="flex items-center justify-between mb-1">
            <span className="text-callout font-semibold text-label-secondary">
              {vendors.length} vendor{vendors.length !== 1 ? "s" : ""}
            </span>
            <button
              type="button"
              onClick={() => setShowAddVendor(true)}
              className="flex items-center gap-1.5 text-callout font-semibold text-accent active:opacity-70"
            >
              <Plus className="h-4 w-4" />
              Add Vendor
            </button>
          </div>

          {vendorLoading ? (
            <p className="py-8 text-center text-callout text-label-secondary">Loading…</p>
          ) : vendors.length === 0 ? (
            <p className="py-8 text-center text-callout text-label-secondary">
              No vendors yet. Add your first vendor to build the registry.
            </p>
          ) : (
            vendors.map((v) => <VendorCard key={v.id} vendor={v} />)
          )}
        </div>
      )}

      {/* FAB — Add Equipment */}
      {activeTab === "equipment" && (
        <button
          type="button"
          onClick={() => setShowAddEquipment(true)}
          className={cn(
            "fixed bottom-20 right-4 z-30",
            "flex h-14 w-14 items-center justify-center",
            "rounded-full bg-accent shadow-lg shadow-accent/30",
            "active:scale-95 transition-transform",
          )}
          aria-label="Add equipment"
        >
          <Plus className="h-6 w-6 text-white" />
        </button>
      )}

      {/* Modals */}
      {showAddEquipment && <AddEquipmentModal onClose={() => setShowAddEquipment(false)} />}
      {showAddVendor && <AddVendorModal onClose={() => setShowAddVendor(false)} />}
    </MobileShell>
  );
}
