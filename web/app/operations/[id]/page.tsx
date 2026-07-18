"use client";

/**
 * /operations/[id] — Campus Detail (Lovable redesign port).
 *
 * Visual source: quill-platform-builder/src/routes/operations.$id.tsx
 * Data: prod hooks from @/lib/api (all verified below).
 *
 * Envelope notes:
 *   useCampus(id)              → Campus (bare object)
 *   useCampusIncidents(id)     → CampusIncidentListResponse { items, total }  → data?.items ?? []
 *   useCampusMetrics(id, days) → CampusMetricListResponse  { items, total }  → data?.items ?? []
 *   useCustomersByCampus(id)   → CustomerListPage { items, total }            → data?.items ?? []
 *
 * Visual changes from old prod:
 *   - ModuleAgentBar added (Lovable shows agent bar on detail screen)
 *   - shadow-card on StatCard + IncidentRow + MetricsTab panels
 *   - Tabs: bg-bg-elevated p-1 → buttons rounded-lg (no outer rounded-xl tab strip with bg-fill-quaternary
 *     since fill-quaternary absent in prod; use bg-bg-elevated instead)
 *   - Severity/status uses text-danger/warning/success tokens
 *   - border-hairline in expanded incident row + modal headers
 *   - Buttons: rounded-full with shadow-card / hover:bg-accent-pressed / active:scale-[0.98]
 *   - DetailsTab: uses useEffect to sync form when campus data loads
 *   - MetricsTab: history list uses shadow-card card, divide-hairline, and metricLabel()
 */

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Loader2,
  Plus,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { MobileShell, TopBar, BackButton } from "@/components/layout/MobileShell";
import { ModuleAgentBar } from "@/components/journey/ModuleAgentBar";
import {
  campusStatusBadge,
  fmtMW,
  fmtPct,
  fmtPUE,
  pueColor,
  uptimeColor,
} from "@/components/operations/CampusCard";
import {
  useCampus,
  useUpdateCampus,
  useCampusIncidents,
  useCreateIncident,
  useUpdateIncident,
  useCampusMetrics,
  useRecordMetric,
  useCustomersByCampus,
} from "@/lib/api";
import type { Campus, CampusIncident, CampusMetric } from "@/lib/schemas";
import { CAMPUS_STATUSES, INCIDENT_SEVERITIES, INCIDENT_STATUSES, METRIC_TYPES } from "@/lib/schemas";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

function severityCls(sev: string): string {
  switch (sev) {
    case "P1": return "bg-danger text-primary-foreground";
    case "P2": return "bg-warning text-primary-foreground";
    case "P3": return "bg-fill-quaternary text-label-secondary";
    default:   return "bg-fill-quaternary text-label-secondary";
  }
}

function statusCls(status: string): string {
  switch (status) {
    case "open":          return "text-danger";
    case "investigating": return "text-warning";
    case "resolved":      return "text-success";
    case "closed":        return "text-label-tertiary";
    default:              return "text-label-secondary";
  }
}

function metricLabel(t: string): string {
  switch (t) {
    case "pue":                return "PUE";
    case "uptime_pct":         return "Uptime %";
    case "power_mw":           return "Live MW";
    case "temp_avg":           return "Avg Temp";
    case "cooling_efficiency": return "Cooling Efficiency";
    default:                   return t;
  }
}

// ── Shared form primitives ────────────────────────────────────────────────────

const fieldInput =
  "w-full rounded-xl bg-bg-elevated shadow-card px-3 py-2.5 text-body text-label-primary placeholder:text-label-tertiary focus:outline-none focus:border-accent";

function FieldRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-caption-1 text-label-secondary">{label}</span>
      {children}
    </label>
  );
}

// ── Modal shell ───────────────────────────────────────────────────────────────

function ModalShell({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 backdrop-blur-sm sm:items-center">
      <div className="w-full max-w-lg rounded-t-2xl sm:rounded-2xl bg-chrome border border-hairline shadow-2xl pb-safe">
        <div className="flex items-center justify-between px-4 pt-4 pb-2 border-b border-hairline">
          <h2 className="text-headline font-semibold text-label-primary">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-label-secondary active:text-label-primary text-body"
          >
            Cancel
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

// ── Stat Card ─────────────────────────────────────────────────────────────────

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
    <div className="flex flex-col gap-1 rounded-2xl bg-bg-elevated shadow-card px-3 py-3">
      <span className="text-caption-2 text-label-tertiary uppercase tracking-wide">{label}</span>
      <span className={cn("text-subhead font-semibold", valueClass ?? "text-label-primary")}>
        {value}
      </span>
      {sub && <span className="text-caption-2 text-label-secondary">{sub}</span>}
    </div>
  );
}

// ── PUE Line Chart ────────────────────────────────────────────────────────────

function PueLineChart({ metrics }: { metrics: CampusMetric[] }) {
  const puePoints = [...metrics]
    .filter((m) => m.metric_type === "pue")
    .sort(
      (a, b) =>
        new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime(),
    );

  if (puePoints.length < 2) {
    return (
      <div className="flex items-center justify-center h-24 text-caption-1 text-label-tertiary">
        {puePoints.length === 0
          ? "No PUE data recorded yet"
          : "Need at least 2 data points for chart"}
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
    <div className="w-full">
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
        {pts.map((p, i) => {
          const [x, y] = p.split(",").map(Number);
          return <circle key={i} cx={x} cy={y} r="3" fill="#0A84FF" />;
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
  const { data, isLoading } = useCampusIncidents(campusId);
  const [expandedId, setExpandedId] = React.useState<string | null>(null);
  const [showLog, setShowLog] = React.useState(false);

  // Prod useCampusIncidents → CampusIncidentListResponse { items, total }
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
        <span className="text-caption-1 text-label-secondary">
          {incidents.length} incident{incidents.length !== 1 ? "s" : ""}
        </span>
        <button
          type="button"
          onClick={() => setShowLog(true)}
          className="flex items-center gap-1.5 rounded-full bg-accent/10 text-accent hover:bg-accent/20 active:scale-[0.98] transition-all px-3 py-1.5 text-caption-1 font-semibold active:opacity-70"
        >
          <Plus className="h-4 w-4" />
          Log Incident
        </button>
      </div>

      {incidents.length === 0 ? (
        <div className="rounded-2xl bg-bg-elevated shadow-card px-6 py-10 text-center">
          <AlertTriangle className="h-8 w-8 text-label-tertiary mx-auto mb-2" />
          <p className="text-body text-label-secondary">No incidents recorded</p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {incidents.map((inc) => (
            <IncidentRow
              key={inc.id}
              incident={inc}
              campusId={campusId}
              expanded={expandedId === inc.id}
              onToggle={() =>
                setExpandedId(expandedId === inc.id ? null : inc.id)
              }
            />
          ))}
        </div>
      )}

      {showLog && (
        <LogIncidentModal campusId={campusId} onClose={() => setShowLog(false)} />
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

  React.useEffect(() => {
    setNewStatus(incident.status);
    setRcaNotes(incident.rca_notes ?? "");
  }, [incident.status, incident.rca_notes]);

  async function handleSave() {
    setSaving(true);
    try {
      await updateIncident.mutateAsync({
        status: newStatus,
        rca_notes: rcaNotes,
      });
    } finally {
      setSaving(false);
    }
  }

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
        className="w-full flex items-center gap-3 px-4 py-3 text-left no-tap-highlight active:opacity-70"
      >
        <span
          className={cn(
            "rounded px-1.5 py-0.5 text-caption-2 font-bold shrink-0",
            severityCls(incident.severity),
          )}
        >
          {incident.severity}
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-body font-medium text-label-primary truncate">
            {incident.title}
          </p>
          <div className="flex items-center gap-2 mt-0.5">
            <span className={cn("text-caption-2 font-semibold", statusCls(incident.status))}>
              {incident.status}
            </span>
            <span className="text-caption-2 text-label-tertiary">·</span>
            <span className="text-caption-2 text-label-tertiary">
              {fmtDate(incident.opened_at)}
            </span>
          </div>
        </div>
        {expanded ? (
          <ChevronUp className="h-4 w-4 text-label-tertiary shrink-0" />
        ) : (
          <ChevronDown className="h-4 w-4 text-label-tertiary shrink-0" />
        )}
      </button>

      {expanded && (
        <div className="px-4 pb-4 border-t border-hairline pt-3 flex flex-col gap-3">
          {incident.description && (
            <p className="text-body text-label-secondary">{incident.description}</p>
          )}
          {incident.impact && (
            <div className="rounded-xl bg-danger/10 border border-danger/20 px-3 py-2">
              <p className="text-caption-2 text-danger font-semibold mb-0.5">
                Customer Impact
              </p>
              <p className="text-caption-1 text-danger">{incident.impact}</p>
            </div>
          )}
          {incident.resolved_at && (
            <p className="text-caption-1 text-label-tertiary">
              Resolved: {fmtDate(incident.resolved_at)}
            </p>
          )}

          <div className="flex flex-col gap-2">
            <label className="text-caption-1 text-label-secondary">Update Status</label>
            <select
              className="rounded-xl bg-bg border border-hairline px-3 py-2 text-body text-label-primary focus:outline-none focus:border-accent"
              value={newStatus}
              onChange={(e) => setNewStatus(e.target.value)}
            >
              {INCIDENT_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s.charAt(0).toUpperCase() + s.slice(1)}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-2">
            <label className="text-caption-1 text-label-secondary">RCA Notes</label>
            <textarea
              className="rounded-xl bg-bg border border-hairline px-3 py-2 text-body text-label-primary focus:outline-none focus:border-accent resize-none"
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
            className="rounded-full bg-accent text-primary-foreground shadow-card hover:bg-accent-pressed hover:shadow-elevated active:scale-[0.98] transition-all py-2 text-body font-semibold active:opacity-70 disabled:opacity-40"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      )}
    </div>
  );
}

function LogIncidentModal({
  campusId,
  onClose,
}: {
  campusId: string;
  onClose: () => void;
}) {
  const createIncident = useCreateIncident(campusId);
  const [title, setTitle] = React.useState("");
  const [severity, setSeverity] = React.useState("P3");
  const [description, setDescription] = React.useState("");
  const [impact, setImpact] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await createIncident.mutateAsync({
        title: title.trim(),
        severity,
        description: description.trim() || null,
        impact: impact.trim() || null,
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <ModalShell title="Log Incident" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-3 px-4 py-4">
        {error && (
          <p className="text-caption-1 text-danger bg-danger/10 rounded-xl px-3 py-2">
            {error}
          </p>
        )}
        <FieldRow label="Title *">
          <input
            className={fieldInput}
            placeholder="Short summary"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
          />
        </FieldRow>
        <FieldRow label="Severity">
          <select
            className={fieldInput}
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
          >
            {INCIDENT_SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </FieldRow>
        <FieldRow label="Description">
          <textarea
            className={cn(fieldInput, "resize-none")}
            rows={3}
            placeholder="What happened?"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </FieldRow>
        <FieldRow label="Customer Impact">
          <textarea
            className={cn(fieldInput, "resize-none")}
            rows={2}
            placeholder="Any user-visible impact?"
            value={impact}
            onChange={(e) => setImpact(e.target.value)}
          />
        </FieldRow>
        <button
          type="submit"
          disabled={!title.trim() || createIncident.isPending}
          className={cn(
            "mt-2 rounded-full bg-accent text-primary-foreground shadow-card hover:bg-accent-pressed hover:shadow-elevated active:scale-[0.98] transition-all py-3 text-body font-semibold",
            (!title.trim() || createIncident.isPending) &&
              "opacity-40 cursor-not-allowed",
          )}
        >
          {createIncident.isPending ? "Logging…" : "Log Incident"}
        </button>
      </form>
    </ModalShell>
  );
}

// ── Metrics Tab ───────────────────────────────────────────────────────────────

function MetricsTab({ campusId }: { campusId: string }) {
  const { data, isLoading } = useCampusMetrics(campusId, 30);
  const [showRecord, setShowRecord] = React.useState(false);

  // Prod useCampusMetrics → CampusMetricListResponse { items, total }
  const metrics = data?.items ?? [];

  const recentDesc = [...metrics].sort((a, b) =>
    b.recorded_at.localeCompare(a.recorded_at),
  );

  if (isLoading) {
    return (
      <div className="flex justify-center py-10 text-label-tertiary">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-2xl bg-bg-elevated shadow-card p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-subhead font-semibold text-label-primary">
            PUE (last 30 days)
          </h3>
          <button
            type="button"
            onClick={() => setShowRecord(true)}
            className="flex items-center gap-1.5 rounded-full bg-accent/10 text-accent hover:bg-accent/20 active:scale-[0.98] transition-all px-3 py-1.5 text-caption-1 font-semibold active:opacity-70"
          >
            <Plus className="h-4 w-4" />
            Record
          </button>
        </div>
        <PueLineChart metrics={metrics} />
      </div>

      <div>
        <h3 className="text-subhead font-semibold text-label-primary mb-2">
          History
        </h3>
        {recentDesc.length === 0 ? (
          <div className="rounded-2xl bg-bg-elevated shadow-card px-4 py-6 text-center text-label-secondary text-body">
            No metrics recorded yet
          </div>
        ) : (
          <div className="rounded-2xl bg-bg-elevated shadow-card overflow-hidden divide-y divide-hairline">
            {recentDesc.slice(0, 20).map((m) => (
              <div
                key={m.id}
                className="flex items-center justify-between px-4 py-2.5"
              >
                <div>
                  <p className="text-body text-label-primary">
                    {metricLabel(m.metric_type)}
                  </p>
                  <p className="text-caption-2 text-label-tertiary">
                    {fmtDate(m.recorded_at)}
                  </p>
                </div>
                <span className="text-body font-mono text-label-primary">
                  {m.metric_type === "pue"
                    ? m.value.toFixed(3)
                    : m.metric_type === "uptime_pct"
                      ? `${m.value.toFixed(3)}%`
                      : m.metric_type === "power_mw"
                        ? `${m.value} MW`
                        : m.value}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {showRecord && (
        <RecordMetricModal campusId={campusId} onClose={() => setShowRecord(false)} />
      )}
    </div>
  );
}

function RecordMetricModal({
  campusId,
  onClose,
}: {
  campusId: string;
  onClose: () => void;
}) {
  const recordMetric = useRecordMetric(campusId);
  const [type, setType] = React.useState("pue");
  const [value, setValue] = React.useState("");
  const [unit, setUnit] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  const defaultUnits: Record<string, string> = {
    pue: "",
    uptime_pct: "%",
    power_mw: "MW",
    temp_avg: "°F",
    cooling_efficiency: "%",
  };

  function handleTypeChange(t: string) {
    setType(t);
    setUnit(defaultUnits[t] ?? "");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const num = parseFloat(value);
    if (Number.isNaN(num)) {
      setError("Enter a valid number");
      return;
    }
    try {
      await recordMetric.mutateAsync({
        metric_type: type,
        value: num,
        unit: unit.trim() || null,
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <ModalShell title="Record Metric" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-3 px-4 py-4">
        {error && (
          <p className="text-caption-1 text-danger bg-danger/10 rounded-xl px-3 py-2">
            {error}
          </p>
        )}
        <FieldRow label="Metric Type">
          <select
            className={fieldInput}
            value={type}
            onChange={(e) => handleTypeChange(e.target.value)}
          >
            {METRIC_TYPES.map((t) => (
              <option key={t} value={t}>
                {metricLabel(t)}
              </option>
            ))}
          </select>
        </FieldRow>
        <div className="grid grid-cols-2 gap-3">
          <FieldRow label="Value *">
            <input
              type="number"
              step="0.001"
              className={fieldInput}
              placeholder="e.g. 1.18"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              required
            />
          </FieldRow>
          <FieldRow label="Unit">
            <input
              className={fieldInput}
              placeholder="%"
              value={unit}
              onChange={(e) => setUnit(e.target.value)}
            />
          </FieldRow>
        </div>
        <button
          type="submit"
          disabled={!value || recordMetric.isPending}
          className={cn(
            "mt-2 rounded-full bg-accent text-primary-foreground shadow-card hover:bg-accent-pressed hover:shadow-elevated active:scale-[0.98] transition-all py-3 text-body font-semibold",
            (!value || recordMetric.isPending) && "opacity-40 cursor-not-allowed",
          )}
        >
          {recordMetric.isPending ? "Recording…" : "Record"}
        </button>
      </form>
    </ModalShell>
  );
}

// ── Details Tab ───────────────────────────────────────────────────────────────

function DetailsTab({ campus }: { campus: Campus }) {
  const updateCampus = useUpdateCampus(campus.id);
  const { data: servingCustomers } = useCustomersByCampus(campus.id);
  // Prod useCustomersByCampus → CustomerListPage { items, total }
  const servingCustomer = servingCustomers?.items?.[0];

  const [name, setName] = React.useState(campus.name);
  const [address, setAddress] = React.useState(campus.address ?? "");
  const [mwLive, setMwLive] = React.useState(campus.mw_live?.toString() ?? "");
  const [mwCapacity, setMwCapacity] = React.useState(campus.mw_capacity?.toString() ?? "");
  const [pueTarget, setPueTarget] = React.useState(campus.pue_target?.toString() ?? "");
  const [campusStatus, setCampusStatus] = React.useState(campus.status);
  const [notes, setNotes] = React.useState(campus.notes ?? "");
  const [projectIdInput, setProjectIdInput] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [savingProject, setSavingProject] = React.useState(false);
  const [saved, setSaved] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // Sync form when campus data refreshes
  React.useEffect(() => {
    setName(campus.name);
    setAddress(campus.address ?? "");
    setMwLive(campus.mw_live?.toString() ?? "");
    setMwCapacity(campus.mw_capacity?.toString() ?? "");
    setPueTarget(campus.pue_target?.toString() ?? "");
    setCampusStatus(campus.status);
    setNotes(campus.notes ?? "");
  }, [campus]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await updateCampus.mutateAsync({
        name: name.trim(),
        address: address.trim() || undefined,
        mw_live: mwLive ? parseFloat(mwLive) : undefined,
        mw_capacity: mwCapacity ? parseFloat(mwCapacity) : undefined,
        pue_target: pueTarget ? parseFloat(pueTarget) : undefined,
        status: campusStatus,
        notes: notes.trim() || undefined,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 1600);
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
    <form onSubmit={handleSave} className="flex flex-col gap-3">
      {error && (
        <p className="text-caption-1 text-danger bg-danger/10 rounded-xl px-3 py-2">{error}</p>
      )}

      <FieldRow label="Name">
        <input
          className={fieldInput}
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
      </FieldRow>
      <FieldRow label="Address">
        <input
          className={fieldInput}
          value={address}
          onChange={(e) => setAddress(e.target.value)}
        />
      </FieldRow>
      <div className="grid grid-cols-2 gap-3">
        <FieldRow label="Live MW">
          <input
            type="number"
            step="0.1"
            className={fieldInput}
            value={mwLive}
            onChange={(e) => setMwLive(e.target.value)}
          />
        </FieldRow>
        <FieldRow label="MW Capacity">
          <input
            type="number"
            step="0.1"
            className={fieldInput}
            value={mwCapacity}
            onChange={(e) => setMwCapacity(e.target.value)}
          />
        </FieldRow>
      </div>
      <FieldRow label="PUE Target">
        <input
          type="number"
          step="0.01"
          min="1"
          max="3"
          className={fieldInput}
          value={pueTarget}
          onChange={(e) => setPueTarget(e.target.value)}
        />
      </FieldRow>
      <FieldRow label="Status">
        <select
          className={fieldInput}
          value={campusStatus}
          onChange={(e) => setCampusStatus(e.target.value)}
        >
          {CAMPUS_STATUSES.map((s) => (
            <option key={s} value={s}>
              {s.charAt(0).toUpperCase() + s.slice(1)}
            </option>
          ))}
        </select>
      </FieldRow>
      <FieldRow label="Notes">
        <textarea
          className={cn(fieldInput, "resize-none")}
          rows={3}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </FieldRow>

      {campus.project_id && (
        <p className="text-caption-1 text-label-tertiary">
          Promoted from project{" "}
          <span className="font-mono">{campus.project_id}</span>
        </p>
      )}

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
              className="flex-1 rounded-xl bg-bg-elevated shadow-card px-3 py-2.5 text-body text-label-primary font-mono text-caption-1 focus:outline-none focus:border-accent"
              placeholder="Project UUID"
              value={projectIdInput}
              onChange={(e) => setProjectIdInput(e.target.value)}
            />
            <button
              type="button"
              onClick={handleLinkProject}
              disabled={!projectIdInput.trim() || savingProject}
              className="rounded-full bg-accent text-primary-foreground shadow-card hover:bg-accent-pressed hover:shadow-elevated active:scale-[0.98] transition-all px-4 py-2.5 text-body font-semibold disabled:opacity-40 shrink-0"
            >
              {savingProject ? "Linking…" : "Link"}
            </button>
          </div>
        </div>
      )}

      {servingCustomer && (
        <div className="rounded-2xl bg-bg-elevated border border-separator/40 px-4 py-3">
          <p className="text-caption-1 text-label-secondary">Serving Customer</p>
          <p className="text-body font-semibold text-label-primary mt-0.5">
            {servingCustomer.name}
          </p>
        </div>
      )}

      <button
        type="submit"
        disabled={saving}
        className={cn(
          "mt-2 rounded-full bg-accent text-primary-foreground shadow-card hover:bg-accent-pressed hover:shadow-elevated active:scale-[0.98] transition-all py-3 text-body font-semibold",
          saving && "opacity-40 cursor-not-allowed",
        )}
      >
        {saving ? "Saving…" : saved ? "Saved" : "Save Changes"}
      </button>
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

function CampusDetailPageInner() {
  const params = useParams();
  const campusId = typeof params.id === "string" ? params.id : (params.id?.[0] ?? "");

  const { data: campus, isLoading, error } = useCampus(campusId);
  const [tab, setTab] = React.useState<TabValue>("incidents");

  if (isLoading) {
    return (
      <MobileShell>
        <TopBar
          left={<BackButton href="/operations" label="Operations" />}
          title="Loading…"
        />
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-label-quaternary" />
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
        <div className="px-4 pt-6 pb-10">
          <div className="rounded-2xl bg-danger/10 px-4 py-4 text-footnote text-danger">
            {error instanceof Error
              ? error.message
              : "Failed to load this campus. Try refreshing."}
          </div>
        </div>
      </MobileShell>
    );
  }

  return (
    <MobileShell>
      <TopBar
        left={<BackButton href="/operations" label="Operations" />}
        title={campus.name}
        right={
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-caption-2 font-semibold",
              campusStatusBadge(campus.status).cls,
            )}
          >
            {campusStatusBadge(campus.status).label}
          </span>
        }
      />
      <ModuleAgentBar moduleKey="operations" />

      <div className="mx-auto w-full max-w-[708px] px-4 pt-3 pb-16 md:max-w-4xl md:px-8">
        {/* ── Header stat cards ──────────────────────────────────────────── */}
        <div className="grid grid-cols-3 gap-2 mb-4">
          <StatCard
            label="Power"
            value={fmtMW(campus.mw_live)}
            sub={campus.mw_capacity != null ? `of ${fmtMW(campus.mw_capacity)}` : undefined}
          />
          <StatCard
            label="PUE"
            value={fmtPUE(campus.pue_current)}
            valueClass={pueColor(campus.pue_current, campus.pue_target)}
            sub={campus.pue_target != null ? `target ${fmtPUE(campus.pue_target)}` : undefined}
          />
          <StatCard
            label="Uptime"
            value={fmtPct(campus.uptime_pct)}
            valueClass={uptimeColor(campus.uptime_pct)}
            sub="30-day"
          />
        </div>

        {/* Active P1/P2 badge row */}
        {campus.active_p1_p2_count > 0 && (
          <div className="flex items-center gap-2 mb-4">
            <span className="inline-flex items-center rounded-full bg-danger/20 px-2 py-0.5 text-caption-2 font-semibold text-danger">
              {campus.active_p1_p2_count} active P1/P2
            </span>
          </div>
        )}

        {/* ── Tabs ──────────────────────────────────────────────────────── */}
        <div className="flex gap-1 rounded-xl bg-bg-elevated p-1 mb-4">
          {TABS.map((t) => (
            <button
              key={t.value}
              type="button"
              onClick={() => setTab(t.value)}
              className={cn(
                "flex-1 rounded-lg px-3 py-2 text-caption-1 font-semibold transition-colors",
                tab === t.value
                  ? "bg-bg text-label-primary shadow"
                  : "text-label-secondary active:opacity-70",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* ── Tab content ───────────────────────────────────────────────── */}
        <div className="pt-2">
          {tab === "incidents" && <IncidentsTab campusId={campus.id} />}
          {tab === "metrics" && <MetricsTab campusId={campus.id} />}
          {tab === "details" && <DetailsTab campus={campus} />}
        </div>
      </div>
    </MobileShell>
  );
}

export default function CampusDetailPage() {
  return (
    <ErrorBoundary moduleName="Operations">
      <CampusDetailPageInner />
    </ErrorBoundary>
  );
}
