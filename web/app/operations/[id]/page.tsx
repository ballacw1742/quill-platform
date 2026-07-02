"use client";

/**
 * /operations/[id] — Campus Detail (Sprint 1A)
 *
 * Tabbed layout:
 *   1. INCIDENTS — list, log new, expand + update
 *   2. METRICS   — PUE line chart (SVG), metric history table, record new
 *   3. DETAILS   — editable campus fields, promote-from-project
 *
 * Design: dark Quill chrome, accent blue #0A84FF, matches /projects patterns.
 */

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  Building2,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Info,
  Loader2,
  Plus,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar, BackButton } from "@/components/layout/MobileShell";
import {
  useCampus,
  useUpdateCampus,
  useCampusIncidents,
  useCreateIncident,
  useUpdateIncident,
  useCampusMetrics,
  useRecordMetric,
} from "@/lib/api";
import type { Campus, CampusIncident, CampusMetric } from "@/lib/schemas";
import { INCIDENT_SEVERITIES, INCIDENT_STATUSES, METRIC_TYPES } from "@/lib/schemas";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtPUE(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toFixed(3);
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v.toFixed(3)}%`;
}

function fmtMW(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v} MW`;
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

function pueColor(current: number | null | undefined, target: number | null | undefined): string {
  if (current == null) return "text-label-primary";
  if (target == null) return "text-label-primary";
  return current <= target ? "text-green-400" : "text-red-400";
}

function uptimeColor(pct: number | null | undefined): string {
  if (pct == null) return "text-label-primary";
  if (pct >= 99.9) return "text-green-400";
  if (pct >= 99.0) return "text-yellow-400";
  return "text-red-400";
}

function campusStatusCls(status: string): string {
  switch (status) {
    case "commissioning": return "text-yellow-400 bg-yellow-400/10";
    case "live":          return "text-green-400 bg-green-400/10";
    case "maintenance":   return "text-orange-400 bg-orange-400/10";
    case "decommissioned": return "text-zinc-400 bg-zinc-400/10";
    default: return "text-label-secondary bg-bg-elevated";
  }
}

function incidentSeverityCls(severity: string): string {
  switch (severity) {
    case "P1": return "bg-red-500 text-white";
    case "P2": return "bg-orange-500 text-white";
    case "P3": return "bg-yellow-500 text-black";
    default:   return "bg-zinc-500 text-white";
  }
}

function incidentStatusCls(status: string): string {
  switch (status) {
    case "open":          return "text-red-400";
    case "investigating": return "text-yellow-400";
    case "resolved":      return "text-green-400";
    case "closed":        return "text-zinc-400";
    default: return "text-label-secondary";
  }
}

// ── Header Stat Card ──────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  valueClass,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  valueClass?: string;
}) {
  return (
    <div className="flex flex-col gap-1 rounded-2xl bg-bg-elevated border border-separator/40 px-3 py-3">
      <span className="text-caption-2 text-label-tertiary uppercase tracking-wide">{label}</span>
      <span className={cn("text-subheadline font-semibold", valueClass ?? "text-label-primary")}>
        {value}
      </span>
      {sub && <span className="text-caption-2 text-label-secondary">{sub}</span>}
    </div>
  );
}

// ── Mini SVG PUE Chart ────────────────────────────────────────────────────────

function PueLineChart({ metrics }: { metrics: CampusMetric[] }) {
  const puePoints = [...metrics]
    .filter((m) => m.metric_type === "pue")
    .sort((a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime());

  if (puePoints.length < 2) {
    return (
      <div className="flex items-center justify-center h-24 text-caption-1 text-label-tertiary">
        {puePoints.length === 0 ? "No PUE data recorded yet" : "Need at least 2 data points for chart"}
      </div>
    );
  }

  const values = puePoints.map((p) => p.value);
  const minV = Math.min(...values);
  const maxV = Math.max(...values);
  const range = maxV - minV || 0.01;
  const W = 300;
  const H = 80;
  const pad = 4;

  const pts = puePoints.map((p, i) => {
    const x = pad + (i / (puePoints.length - 1)) * (W - pad * 2);
    const y = pad + ((maxV - p.value) / range) * (H - pad * 2);
    return `${x},${y}`;
  });

  return (
    <div className="w-full overflow-x-auto">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-20"
        preserveAspectRatio="none"
      >
        <polyline
          points={pts.join(" ")}
          fill="none"
          stroke="#0A84FF"
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {puePoints.map((p, i) => {
          const [x, y] = pts[i].split(",").map(Number);
          return (
            <circle key={i} cx={x} cy={y} r="3" fill="#0A84FF" />
          );
        })}
      </svg>
      <div className="flex justify-between text-caption-2 text-label-tertiary mt-1 px-1">
        <span>{fmtDate(puePoints[0].recorded_at)}</span>
        <span>{fmtDate(puePoints[puePoints.length - 1].recorded_at)}</span>
      </div>
    </div>
  );
}

// ── Incidents Tab ─────────────────────────────────────────────────────────────

function IncidentsTab({ campusId }: { campusId: string }) {
  const { data, isLoading, error } = useCampusIncidents(campusId);
  const createIncident = useCreateIncident(campusId);
  const [expandedId, setExpandedId] = React.useState<string | null>(null);
  const [showLogModal, setShowLogModal] = React.useState(false);

  const incidents = data?.items ?? [];

  if (isLoading) {
    return (
      <div className="flex justify-center py-10 text-label-tertiary">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <span className="text-caption-1 text-label-secondary">{incidents.length} incident{incidents.length !== 1 ? "s" : ""}</span>
        <button
          type="button"
          onClick={() => setShowLogModal(true)}
          className="flex items-center gap-1.5 rounded-xl bg-accent/10 text-accent px-3 py-1.5 text-caption-1 font-semibold active:opacity-70"
        >
          <Plus className="h-4 w-4" />
          Log Incident
        </button>
      </div>

      {incidents.length === 0 ? (
        <div className="rounded-2xl bg-bg-elevated border border-separator/40 px-6 py-10 text-center">
          <AlertTriangle className="h-8 w-8 text-label-tertiary mx-auto mb-2" />
          <p className="text-body text-label-secondary">No incidents recorded</p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {incidents.map((incident) => (
            <IncidentRow
              key={incident.id}
              incident={incident}
              campusId={campusId}
              expanded={expandedId === incident.id}
              onToggle={() => setExpandedId(expandedId === incident.id ? null : incident.id)}
            />
          ))}
        </div>
      )}

      {showLogModal && (
        <LogIncidentModal campusId={campusId} onClose={() => setShowLogModal(false)} />
      )}
    </div>
  );
}

function IncidentRow({
  incident,
  campusId,
  expanded,
  onToggle,
}: {
  incident: CampusIncident;
  campusId: string;
  expanded: boolean;
  onToggle: () => void;
}) {
  const updateIncident = useUpdateIncident(campusId, incident.id);
  const [newStatus, setNewStatus] = React.useState(incident.status);
  const [rcaNotes, setRcaNotes] = React.useState(incident.rca_notes ?? "");
  const [saving, setSaving] = React.useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      await updateIncident.mutateAsync({
        status: newStatus,
        rca_notes: rcaNotes || undefined,
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={cn(
      "rounded-2xl bg-bg-elevated border border-separator/40 overflow-hidden",
      expanded && "border-accent/30",
    )}>
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-4 py-3 text-left no-tap-highlight active:opacity-70"
      >
        <span className={cn("rounded px-1.5 py-0.5 text-caption-2 font-bold shrink-0", incidentSeverityCls(incident.severity))}>
          {incident.severity}
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-body font-medium text-label-primary truncate">{incident.title}</p>
          <div className="flex items-center gap-2 mt-0.5">
            <span className={cn("text-caption-2 font-semibold", incidentStatusCls(incident.status))}>
              {incident.status}
            </span>
            <span className="text-caption-2 text-label-tertiary">·</span>
            <span className="text-caption-2 text-label-tertiary">{fmtDate(incident.opened_at)}</span>
          </div>
        </div>
        {expanded ? (
          <ChevronUp className="h-4 w-4 text-label-tertiary shrink-0" />
        ) : (
          <ChevronDown className="h-4 w-4 text-label-tertiary shrink-0" />
        )}
      </button>

      {expanded && (
        <div className="px-4 pb-4 border-t border-separator/20 pt-3 flex flex-col gap-3">
          {incident.description && (
            <p className="text-body text-label-secondary">{incident.description}</p>
          )}
          {incident.impact && (
            <div className="rounded-xl bg-red-500/10 border border-red-500/20 px-3 py-2">
              <p className="text-caption-2 text-red-300 font-semibold mb-0.5">Customer Impact</p>
              <p className="text-caption-1 text-red-200">{incident.impact}</p>
            </div>
          )}
          {incident.resolved_at && (
            <p className="text-caption-1 text-label-tertiary">
              Resolved: {fmtDate(incident.resolved_at)}
            </p>
          )}

          {/* Update status */}
          <div className="flex flex-col gap-2">
            <label className="text-caption-1 text-label-secondary">Update Status</label>
            <select
              className="rounded-xl bg-bg border border-separator/40 px-3 py-2 text-body text-label-primary focus:outline-none focus:border-accent"
              value={newStatus}
              onChange={(e) => setNewStatus(e.target.value)}
            >
              {INCIDENT_STATUSES.map((s) => (
                <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
              ))}
            </select>
          </div>

          {/* RCA Notes */}
          <div className="flex flex-col gap-2">
            <label className="text-caption-1 text-label-secondary">RCA Notes</label>
            <textarea
              className="rounded-xl bg-bg border border-separator/40 px-3 py-2 text-body text-label-primary focus:outline-none focus:border-accent resize-none"
              rows={3}
              placeholder="Root cause analysis notes…"
              value={rcaNotes}
              onChange={(e) => setRcaNotes(e.target.value)}
            />
          </div>

          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="rounded-xl bg-accent text-white py-2 text-body font-semibold active:opacity-70 disabled:opacity-40"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      )}
    </div>
  );
}

function LogIncidentModal({ campusId, onClose }: { campusId: string; onClose: () => void }) {
  const createIncident = useCreateIncident(campusId);
  const [title, setTitle] = React.useState("");
  const [severity, setSeverity] = React.useState<string>("P3");
  const [description, setDescription] = React.useState("");
  const [impact, setImpact] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await createIncident.mutateAsync({ title, severity, description: description || null, impact: impact || null });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 backdrop-blur-sm sm:items-center">
      <div className="w-full max-w-lg rounded-t-2xl sm:rounded-2xl bg-chrome border border-separator/40 shadow-2xl pb-safe">
        <div className="flex items-center justify-between px-4 pt-4 pb-2 border-b border-separator/30">
          <h2 className="text-headline font-semibold text-label-primary">Log Incident</h2>
          <button type="button" onClick={onClose} className="text-label-secondary text-body">Cancel</button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3 px-4 py-4">
          {error && <p className="text-caption-1 text-red-400 bg-red-400/10 rounded-xl px-3 py-2">{error}</p>}

          <label className="flex flex-col gap-1">
            <span className="text-caption-1 text-label-secondary">Title *</span>
            <input
              className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2.5 text-body text-label-primary focus:outline-none focus:border-accent"
              placeholder="Brief description of the incident"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-caption-1 text-label-secondary">Severity</span>
            <select
              className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2.5 text-body text-label-primary focus:outline-none focus:border-accent"
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
            >
              {INCIDENT_SEVERITIES.map((s) => (
                <option key={s} value={s}>
                  {s === "P1" ? "P1 — Critical (customer-impacting)" :
                   s === "P2" ? "P2 — High (service degraded)" :
                   s === "P3" ? "P3 — Medium" :
                   "P4 — Low / Informational"}
                </option>
              ))}
            </select>
            {severity === "P1" && (
              <p className="text-caption-2 text-red-400 mt-1">⚠ P1 incidents require immediate COO notification.</p>
            )}
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-caption-1 text-label-secondary">Description</span>
            <textarea
              className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2.5 text-body text-label-primary focus:outline-none focus:border-accent resize-none"
              rows={3}
              placeholder="Detailed description of the issue"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-caption-1 text-label-secondary">Customer Impact</span>
            <textarea
              className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2.5 text-body text-label-primary focus:outline-none focus:border-accent resize-none"
              rows={2}
              placeholder="What customers / workloads are affected"
              value={impact}
              onChange={(e) => setImpact(e.target.value)}
            />
          </label>

          <button
            type="submit"
            disabled={!title.trim() || createIncident.isPending}
            className="mt-2 w-full rounded-xl py-3 text-body font-semibold bg-accent text-white disabled:opacity-40"
          >
            {createIncident.isPending ? "Logging…" : "Log Incident"}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── Metrics Tab ───────────────────────────────────────────────────────────────

function MetricsTab({ campusId }: { campusId: string }) {
  const { data, isLoading } = useCampusMetrics(campusId, 30);
  const recordMetric = useRecordMetric(campusId);
  const [showRecordModal, setShowRecordModal] = React.useState(false);

  const metrics = data?.items ?? [];
  const displayMetrics = [...metrics].slice(0, 50);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <span className="text-caption-1 text-label-secondary">{metrics.length} readings (last 30 days)</span>
        <button
          type="button"
          onClick={() => setShowRecordModal(true)}
          className="flex items-center gap-1.5 rounded-xl bg-accent/10 text-accent px-3 py-1.5 text-caption-1 font-semibold active:opacity-70"
        >
          <Plus className="h-4 w-4" />
          Record Metric
        </button>
      </div>

      {/* PUE Chart */}
      <div className="rounded-2xl bg-bg-elevated border border-separator/40 px-4 py-4">
        <p className="text-caption-1 text-label-secondary mb-3 font-semibold">PUE — Last 30 Days</p>
        {isLoading ? (
          <div className="flex justify-center py-6"><Loader2 className="h-5 w-5 animate-spin text-label-tertiary" /></div>
        ) : (
          <PueLineChart metrics={metrics} />
        )}
      </div>

      {/* Metric history table */}
      {metrics.length > 0 && (
        <div className="rounded-2xl bg-bg-elevated border border-separator/40 overflow-hidden">
          <div className="grid grid-cols-4 gap-2 px-4 py-2 border-b border-separator/30">
            {["Type", "Value", "Unit", "Recorded"].map((h) => (
              <span key={h} className="text-caption-2 text-label-tertiary font-semibold uppercase tracking-wide">{h}</span>
            ))}
          </div>
          <div className="divide-y divide-separator/20">
            {displayMetrics.map((m) => (
              <div key={m.id} className="grid grid-cols-4 gap-2 px-4 py-2.5 items-center">
                <span className="text-caption-1 text-label-primary font-medium">{m.metric_type}</span>
                <span className="text-caption-1 text-label-primary">{m.value}</span>
                <span className="text-caption-1 text-label-secondary">{m.unit ?? "—"}</span>
                <span className="text-caption-2 text-label-tertiary">{fmtDate(m.recorded_at)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {!isLoading && metrics.length === 0 && (
        <div className="rounded-2xl bg-bg-elevated border border-separator/40 px-6 py-10 text-center">
          <Activity className="h-8 w-8 text-label-tertiary mx-auto mb-2" />
          <p className="text-body text-label-secondary">No metrics recorded yet</p>
        </div>
      )}

      {showRecordModal && (
        <RecordMetricModal campusId={campusId} onClose={() => setShowRecordModal(false)} />
      )}
    </div>
  );
}

function RecordMetricModal({ campusId, onClose }: { campusId: string; onClose: () => void }) {
  const recordMetric = useRecordMetric(campusId);
  const [metricType, setMetricType] = React.useState<string>("pue");
  const [value, setValue] = React.useState("");
  const [unit, setUnit] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  // Default units per metric type
  const defaultUnits: Record<string, string> = {
    pue: "",
    uptime_pct: "%",
    power_mw: "MW",
    temp_avg: "°F",
    cooling_efficiency: "%",
  };

  function handleTypeChange(t: string) {
    setMetricType(t);
    setUnit(defaultUnits[t] ?? "");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await recordMetric.mutateAsync({
        metric_type: metricType,
        value: parseFloat(value),
        unit: unit.trim() || null,
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 backdrop-blur-sm sm:items-center">
      <div className="w-full max-w-lg rounded-t-2xl sm:rounded-2xl bg-chrome border border-separator/40 shadow-2xl pb-safe">
        <div className="flex items-center justify-between px-4 pt-4 pb-2 border-b border-separator/30">
          <h2 className="text-headline font-semibold text-label-primary">Record Metric</h2>
          <button type="button" onClick={onClose} className="text-label-secondary text-body">Cancel</button>
        </div>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3 px-4 py-4">
          {error && <p className="text-caption-1 text-red-400 bg-red-400/10 rounded-xl px-3 py-2">{error}</p>}

          <label className="flex flex-col gap-1">
            <span className="text-caption-1 text-label-secondary">Metric Type</span>
            <select
              className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2.5 text-body text-label-primary focus:outline-none focus:border-accent"
              value={metricType}
              onChange={(e) => handleTypeChange(e.target.value)}
            >
              {METRIC_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-caption-1 text-label-secondary">Value *</span>
              <input
                type="number"
                step="any"
                className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2.5 text-body text-label-primary focus:outline-none focus:border-accent"
                placeholder="1.18"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                required
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-caption-1 text-label-secondary">Unit</span>
              <input
                className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2.5 text-body text-label-primary focus:outline-none focus:border-accent"
                placeholder="%"
                value={unit}
                onChange={(e) => setUnit(e.target.value)}
              />
            </label>
          </div>

          <button
            type="submit"
            disabled={!value || recordMetric.isPending}
            className="mt-2 w-full rounded-xl py-3 text-body font-semibold bg-accent text-white disabled:opacity-40"
          >
            {recordMetric.isPending ? "Recording…" : "Record"}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── Details Tab ───────────────────────────────────────────────────────────────

function DetailsTab({ campus }: { campus: Campus }) {
  const updateCampus = useUpdateCampus(campus.id);
  const [name, setName] = React.useState(campus.name);
  const [address, setAddress] = React.useState(campus.address ?? "");
  const [mwCapacity, setMwCapacity] = React.useState(String(campus.mw_capacity ?? ""));
  const [mwLive, setMwLive] = React.useState(String(campus.mw_live ?? ""));
  const [pueTarget, setPueTarget] = React.useState(String(campus.pue_target ?? ""));
  const [notes, setNotes] = React.useState(campus.notes ?? "");
  const [projectIdInput, setProjectIdInput] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [savingProject, setSavingProject] = React.useState(false);
  const [success, setSuccess] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await updateCampus.mutateAsync({
        name: name.trim(),
        address: address.trim() || undefined,
        mw_capacity: mwCapacity ? parseFloat(mwCapacity) : undefined,
        mw_live: mwLive ? parseFloat(mwLive) : undefined,
        pue_target: pueTarget ? parseFloat(pueTarget) : undefined,
        notes: notes.trim() || undefined,
      });
      setSuccess(true);
      setTimeout(() => setSuccess(false), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleLinkProject() {
    if (!projectIdInput.trim()) return;
    setSavingProject(true);
    setError(null);
    try {
      await updateCampus.mutateAsync({ project_id: projectIdInput.trim() });
      setProjectIdInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to link project");
    } finally {
      setSavingProject(false);
    }
  }

  return (
    <form onSubmit={handleSave} className="flex flex-col gap-4">
      {error && <p className="text-caption-1 text-red-400 bg-red-400/10 rounded-xl px-3 py-2">{error}</p>}
      {success && <p className="text-caption-1 text-green-400 bg-green-400/10 rounded-xl px-3 py-2">Saved ✓</p>}

      <div className="rounded-2xl bg-bg-elevated border border-separator/40 px-4 py-4 flex flex-col gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-caption-1 text-label-secondary">Campus Name</span>
          <input
            className="w-full rounded-xl bg-bg border border-separator/40 px-3 py-2.5 text-body text-label-primary focus:outline-none focus:border-accent"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-caption-1 text-label-secondary">Address</span>
          <input
            className="w-full rounded-xl bg-bg border border-separator/40 px-3 py-2.5 text-body text-label-primary focus:outline-none focus:border-accent"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
          />
        </label>

        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-caption-1 text-label-secondary">MW Capacity</span>
            <input
              type="number"
              step="0.1"
              min="0"
              className="w-full rounded-xl bg-bg border border-separator/40 px-3 py-2.5 text-body text-label-primary focus:outline-none focus:border-accent"
              value={mwCapacity}
              onChange={(e) => setMwCapacity(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-caption-1 text-label-secondary">MW Live</span>
            <input
              type="number"
              step="0.1"
              min="0"
              className="w-full rounded-xl bg-bg border border-separator/40 px-3 py-2.5 text-body text-label-primary focus:outline-none focus:border-accent"
              value={mwLive}
              onChange={(e) => setMwLive(e.target.value)}
            />
          </label>
        </div>

        <label className="flex flex-col gap-1">
          <span className="text-caption-1 text-label-secondary">PUE Target</span>
          <input
            type="number"
            step="0.01"
            min="1"
            max="3"
            className="w-full rounded-xl bg-bg border border-separator/40 px-3 py-2.5 text-body text-label-primary focus:outline-none focus:border-accent"
            value={pueTarget}
            onChange={(e) => setPueTarget(e.target.value)}
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-caption-1 text-label-secondary">Notes</span>
          <textarea
            className="w-full rounded-xl bg-bg border border-separator/40 px-3 py-2.5 text-body text-label-primary focus:outline-none focus:border-accent resize-none"
            rows={3}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </label>

        <button
          type="submit"
          disabled={saving}
          className="w-full rounded-xl py-3 text-body font-semibold bg-accent text-white disabled:opacity-40 active:opacity-70"
        >
          {saving ? "Saving…" : "Save Changes"}
        </button>
      </div>

      {/* Promote from Project */}
      {!campus.project_id && (
        <div className="rounded-2xl bg-bg-elevated border border-separator/40 px-4 py-4 flex flex-col gap-3">
          <div>
            <p className="text-body font-semibold text-label-primary">Link to Project</p>
            <p className="text-caption-1 text-label-secondary mt-0.5">
              Associate this campus with a construction project ID.
            </p>
          </div>
          <div className="flex gap-2">
            <input
              className="flex-1 rounded-xl bg-bg border border-separator/40 px-3 py-2.5 text-body text-label-primary font-mono text-caption-1 focus:outline-none focus:border-accent"
              placeholder="Project UUID"
              value={projectIdInput}
              onChange={(e) => setProjectIdInput(e.target.value)}
            />
            <button
              type="button"
              onClick={handleLinkProject}
              disabled={!projectIdInput.trim() || savingProject}
              className="rounded-xl bg-accent text-white px-4 py-2.5 text-body font-semibold disabled:opacity-40 active:opacity-70 shrink-0"
            >
              {savingProject ? "Linking…" : "Link"}
            </button>
          </div>
        </div>
      )}

      {campus.project_id && (
        <div className="rounded-2xl bg-bg-elevated border border-separator/40 px-4 py-3">
          <p className="text-caption-1 text-label-secondary">Linked Project</p>
          <p className="text-body font-mono text-label-primary mt-0.5">{campus.project_id}</p>
        </div>
      )}
    </form>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

type TabValue = "incidents" | "metrics" | "details";

const TABS: { label: string; value: TabValue }[] = [
  { label: "Incidents", value: "incidents" },
  { label: "Metrics", value: "metrics" },
  { label: "Details", value: "details" },
];

export default function CampusDetailPage() {
  const params = useParams();
  const router = useRouter();
  const campusId = typeof params.id === "string" ? params.id : (params.id?.[0] ?? "");

  const { data: campusRaw, isLoading, error } = useCampus(campusId);
  const campus = campusRaw as Campus | undefined;
  const [tab, setTab] = React.useState<TabValue>("incidents");

  if (isLoading) {
    return (
      <MobileShell>
        <TopBar
          left={<BackButton href="/operations" label="Operations" />}
          title="Loading…"
        />
        <div className="flex justify-center pt-20">
          <Loader2 className="h-6 w-6 animate-spin text-label-tertiary" />
        </div>
      </MobileShell>
    );
  }

  if (error || !campus) {
    return (
      <MobileShell>
        <TopBar
          left={<BackButton href="/operations" label="Operations" />}
          title="Campus"
        />
        <div className="px-4 py-6 text-center text-label-secondary text-body">
          {error instanceof Error ? error.message : "Campus not found"}
        </div>
      </MobileShell>
    );
  }

  const statusCls = campusStatusCls(campus.status);

  return (
    <MobileShell>
      <TopBar
        left={<BackButton href="/operations" label="Operations" />}
        title={campus.name}
        right={
          <span className={cn("rounded-full px-2 py-0.5 text-caption-2 font-semibold", statusCls)}>
            {campus.status}
          </span>
        }
      />

      <div className="px-4 py-4 flex flex-col gap-4 pb-8">
        {/* ── Header Stat Cards ─────────────────────────────────────────── */}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <StatCard
            label="PUE"
            value={fmtPUE(campus.pue_current)}
            sub={campus.pue_target ? `target ${fmtPUE(campus.pue_target)}` : "no target set"}
            valueClass={pueColor(campus.pue_current, campus.pue_target)}
          />
          <StatCard
            label="Uptime"
            value={fmtPct(campus.uptime_pct)}
            sub="30-day rolling"
            valueClass={uptimeColor(campus.uptime_pct)}
          />
          <StatCard
            label="Power"
            value={fmtMW(campus.power_mw_current)}
            sub={campus.mw_capacity != null ? `/ ${fmtMW(campus.mw_capacity)} cap` : "capacity unknown"}
          />
          <StatCard
            label="Incidents"
            value={campus.active_p1_p2_count > 0 ? `${campus.active_p1_p2_count} active` : "Clear"}
            sub="P1 / P2 open"
            valueClass={campus.active_p1_p2_count > 0 ? "text-red-400" : "text-green-400"}
          />
        </div>

        {/* ── Tabs ──────────────────────────────────────────────────────── */}
        <div className="flex gap-1 rounded-2xl bg-bg-elevated border border-separator/40 p-1">
          {TABS.map((t) => (
            <button
              key={t.value}
              type="button"
              onClick={() => setTab(t.value)}
              className={cn(
                "flex-1 rounded-xl py-2 text-body font-semibold transition-colors no-tap-highlight",
                tab === t.value
                  ? "bg-accent text-white shadow-sm"
                  : "text-label-secondary active:text-label-primary",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* ── Tab Content ───────────────────────────────────────────────── */}
        {tab === "incidents" && <IncidentsTab campusId={campusId} />}
        {tab === "metrics" && <MetricsTab campusId={campusId} />}
        {tab === "details" && campus && <DetailsTab campus={campus} />}
      </div>
    </MobileShell>
  );
}
