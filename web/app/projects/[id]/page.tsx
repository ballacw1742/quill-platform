"use client";

/**
 * /projects/[id] — Project detail (Sprint DC.2 + 0.2 hardening)
 *
 * Tabbed layout with 4 tabs:
 *   1. Overview  — phase stepper, budget cards, notes, site linkage
 *   2. Milestones — list, add, mark complete, overdue highlights
 *   3. Log        — construction log feed, add entry
 *   4. Links      — documents, contracts, estimates
 *
 * Design: dark Quill theme, iOS-style cards, matches /contracts tab pattern.
 */

import * as React from "react";
import { useRouter, useParams } from "next/navigation";
import {
  ArrowLeft,
  ChevronRight,
  DollarSign,
  ExternalLink,
  FileText,
  Loader2,
  MapPin,
  Pencil,
  Plus,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { SegmentedControl } from "@/components/ui/segmented-control";
import {
  useProject,
  useUpdateProject,
  useProjectMilestones,
  useCreateMilestone,
  useUpdateMilestone,
  useDeleteMilestone,
  useProjectLog,
  useAddLogEntry,
  useUpdateProjectBudget,
  useProjectDocumentLinks,
  useAddDocumentLink,
  useProjectContractLinks,
  useLinkContract,
  useProjectEstimateLinks,
  useLinkEstimate,
  useContractsList,
  useListEstimates,
  useCampusesByProject,
  useCreateCampus,
  useDeployTemplateCatalog,
  useDeployCampusFromTemplate,
} from "@/lib/api";
import type {
  QuillProject,
  ProjectMilestone,
  ProjectLogEntry,
  ProjectDocumentLink,
  DeploymentReport,
} from "@/lib/schemas";

// ── Tab types ─────────────────────────────────────────────────────────────────

type TabValue = "overview" | "milestones" | "log" | "links";

const TABS: { label: string; value: TabValue }[] = [
  { label: "Overview", value: "overview" },
  { label: "Milestones", value: "milestones" },
  { label: "Log", value: "log" },
  { label: "Links", value: "links" },
];

// ── Phase config ──────────────────────────────────────────────────────────────

const PHASES = [
  { key: "site_control", label: "Site Control" },
  { key: "permitting", label: "Permitting" },
  { key: "design", label: "Design" },
  { key: "construction", label: "Construction" },
  { key: "commissioning", label: "Commissioning" },
  { key: "turnover", label: "Turnover" },
] as const;

function phaseIndex(phase: string): number {
  return PHASES.findIndex((p) => p.key === phase);
}

// ── Shared helpers ────────────────────────────────────────────────────────────

function statusBadge(status: string): { label: string; cls: string } {
  switch (status) {
    case "active": return { label: "Active", cls: "text-green-400 bg-green-400/10" };
    case "on_hold": return { label: "On Hold", cls: "text-yellow-400 bg-yellow-400/10" };
    case "complete": return { label: "Complete", cls: "text-blue-400 bg-blue-400/10" };
    case "cancelled": return { label: "Cancelled", cls: "text-red-400 bg-red-400/10" };
    default: return { label: status, cls: "text-label-secondary bg-bg-elevated" };
  }
}

function verdictLabel(verdict: string | null | undefined): { label: string; cls: string } | null {
  switch (verdict) {
    case "strong_recommend": return { label: "Strong Recommend", cls: "text-green-400 bg-green-400/10" };
    case "conditional": return { label: "Conditional", cls: "text-blue-400 bg-blue-400/10" };
    case "weak": return { label: "Weak", cls: "text-yellow-400 bg-yellow-400/10" };
    case "no_go": return { label: "No-Go", cls: "text-red-400 bg-red-400/10" };
    default: return null;
  }
}

function workloadLabel(wt: string | null | undefined): string {
  switch (wt) {
    case "hyperscale_compute":
    case "hyperscale": return "Hyperscale";
    case "ai_hpc": return "AI/HPC";
    case "edge_latency":
    case "edge": return "Edge";
    case "colocation":
    case "enterprise_colo": return "Colo";
    case "mixed": return "Mixed";
    default: return wt ?? "";
  }
}

function scoreColor(score: number | null | undefined): string {
  if (score == null) return "text-label-tertiary";
  if (score >= 70) return "text-green-400";
  if (score >= 50) return "text-yellow-400";
  return "text-red-400";
}

function formatUSD(val: number | null | undefined): string {
  if (val == null) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(val);
}

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-2xl bg-chrome/80 border border-separator/40 p-5 mb-4", className)}>
      {children}
    </div>
  );
}

// ── Phase Stepper ─────────────────────────────────────────────────────────────

function PhaseStepper({ phase }: { phase: string }) {
  const currentIdx = phaseIndex(phase);
  return (
    <div className="space-y-1">
      {PHASES.map((p, i) => {
        const done = i < currentIdx;
        const active = i === currentIdx;
        const future = i > currentIdx;
        return (
          <div key={p.key} className="flex items-center gap-3">
            <div className={cn(
              "w-6 h-6 rounded-full border-2 flex items-center justify-center shrink-0 text-caption-1 font-bold",
              done && "border-accent bg-accent text-white",
              active && "border-accent bg-accent/10 text-accent",
              future && "border-separator/40 bg-transparent text-label-quaternary",
            )}>
              {done ? "✓" : i + 1}
            </div>
            <span className={cn(
              "text-callout",
              done && "text-label-secondary",
              active && "text-label-primary font-semibold",
              future && "text-label-quaternary",
            )}>
              {p.label}
            </span>
            {active && <span className="ml-auto text-caption-1 font-semibold text-accent">Current</span>}
          </div>
        );
      })}
    </div>
  );
}

// ── Budget Section ────────────────────────────────────────────────────────────

function BudgetSection({ project }: { project: QuillProject }) {
  const updateBudget = useUpdateProjectBudget(project.id);
  const [editing, setEditing] = React.useState(false);
  const [budget, setBudget] = React.useState(String(project.budget_usd ?? ""));
  const [committed, setCommitted] = React.useState(String(project.committed_usd ?? ""));
  const [forecast, setForecast] = React.useState(String(project.forecast_usd ?? ""));

  function handleSave() {
    updateBudget.mutate(
      {
        budget_usd: budget ? parseFloat(budget) : null,
        committed_usd: committed ? parseFloat(committed) : null,
        forecast_usd: forecast ? parseFloat(forecast) : null,
      },
      { onSuccess: () => setEditing(false) },
    );
  }

  const isOverBudget =
    project.forecast_usd != null &&
    project.budget_usd != null &&
    project.forecast_usd > project.budget_usd;

  if (editing) {
    return (
      <Card>
        <div className="flex items-center justify-between mb-3">
          <p className="text-callout font-semibold text-label-primary">Budget</p>
          <button type="button" onClick={() => setEditing(false)} className="text-label-quaternary">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-3">
          {[
            { label: "Budget", val: budget, set: setBudget },
            { label: "Committed", val: committed, set: setCommitted },
            { label: "Forecast", val: forecast, set: setForecast },
          ].map(({ label, val, set }) => (
            <div key={label}>
              <label className="block text-footnote font-semibold text-label-secondary uppercase tracking-wide mb-1">
                {label} (USD)
              </label>
              <input
                type="number"
                value={val}
                onChange={(e) => set(e.target.value)}
                placeholder="0"
                className="w-full rounded-xl px-4 py-2.5 text-body text-label-primary bg-bg-elevated border border-separator/60 placeholder:text-label-quaternary focus:outline-none focus:border-accent"
              />
            </div>
          ))}
        </div>
        <div className="flex gap-3 mt-4">
          <button
            type="button"
            disabled={updateBudget.isPending}
            onClick={handleSave}
            className="flex-1 py-2.5 rounded-xl bg-accent text-white font-semibold text-callout disabled:opacity-60"
          >
            {updateBudget.isPending ? "Saving…" : "Save"}
          </button>
          <button
            type="button"
            onClick={() => setEditing(false)}
            className="flex-1 py-2.5 rounded-xl border border-separator/60 text-label-primary font-semibold text-callout"
          >
            Cancel
          </button>
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <p className="text-callout font-semibold text-label-primary">Budget</p>
        <div className="flex items-center gap-2">
          {isOverBudget && (
            <span className="text-caption-1 font-semibold text-red-400 bg-red-400/10 rounded-full px-2 py-0.5">
              Over Budget
            </span>
          )}
          <button type="button" onClick={() => setEditing(true)} className="text-accent text-callout flex items-center gap-1">
            <Pencil className="h-3.5 w-3.5" /> Edit
          </button>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: "Budget", val: project.budget_usd },
          { label: "Committed", val: project.committed_usd },
          { label: "Forecast", val: project.forecast_usd, overBudget: isOverBudget },
        ].map(({ label, val, overBudget }) => (
          <div key={label} className="rounded-xl bg-bg-elevated px-3 py-2.5">
            <p className="text-caption-2 font-semibold text-label-tertiary uppercase tracking-wide mb-1">{label}</p>
            <p className={cn("text-subhead font-bold tabular-nums", overBudget ? "text-red-400" : "text-label-primary")}>
              {formatUSD(val)}
            </p>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ── Notes Section ─────────────────────────────────────────────────────────────

function NotesSection({ project }: { project: QuillProject }) {
  const updateProject = useUpdateProject();
  const [editing, setEditing] = React.useState(false);
  const [value, setValue] = React.useState(project.notes ?? "");

  function handleSave() {
    updateProject.mutate(
      { id: project.id, body: { notes: value } },
      { onSuccess: () => setEditing(false) },
    );
  }

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <p className="text-callout font-semibold text-label-primary">Notes</p>
        {!editing && (
          <button type="button" onClick={() => setEditing(true)} className="text-accent text-callout flex items-center gap-1">
            <Pencil className="h-3.5 w-3.5" /> Edit
          </button>
        )}
      </div>
      {editing ? (
        <>
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            rows={4}
            placeholder="Add notes about this project…"
            className="w-full rounded-xl px-4 py-3 text-body text-label-primary bg-bg-elevated border border-separator/60 placeholder:text-label-quaternary focus:outline-none focus:border-accent resize-none"
            autoFocus
          />
          <div className="flex gap-3 mt-3">
            <button
              type="button"
              disabled={updateProject.isPending}
              onClick={handleSave}
              className="flex-1 py-2.5 rounded-xl bg-accent text-white font-semibold text-callout disabled:opacity-60"
            >
              {updateProject.isPending ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              onClick={() => { setValue(project.notes ?? ""); setEditing(false); }}
              className="flex-1 py-2.5 rounded-xl border border-separator/60 text-label-primary font-semibold text-callout"
            >
              Cancel
            </button>
          </div>
        </>
      ) : (
        <p className={cn("text-callout leading-relaxed", value ? "text-label-secondary" : "text-label-quaternary")}>
          {value || "No notes yet. Tap Edit to add."}
        </p>
      )}
    </Card>
  );
}

// ── Overview Tab ──────────────────────────────────────────────────────────────

// ── Campus Template Deploy (Sprint 5.4) ────────────────────────────────────────

const DEPLOY_STEP_LABELS: Record<string, string> = {
  campus: "Campus Record",
  monitoring_agents: "Monitoring Agents",
  equipment: "Equipment",
  compliance_checklist: "Compliance Checklist",
  vendors: "Vendors",
  dashboard_seed: "Dashboard Seed",
};

function deployStepLabel(step: string): string {
  return DEPLOY_STEP_LABELS[step] ?? step;
}

/** FastAPI errors arrive as `{ "detail": "..." }` — show `detail` to the user. */
function errorDetail(err: unknown): string {
  const msg = err instanceof Error ? err.message : String(err);
  try {
    const parsed = JSON.parse(msg) as { detail?: unknown };
    if (parsed && typeof parsed.detail === "string") return parsed.detail;
  } catch {
    /* not JSON — fall through */
  }
  return msg;
}

function DeploymentReportView({ report, onDismiss }: { report: DeploymentReport; onDismiss: () => void }) {
  const router = useRouter();
  return (
    <>
      <div className="flex items-center justify-between mb-2">
        <p className="text-callout font-semibold text-label-primary">Deployment Report</p>
        <button type="button" onClick={onDismiss} className="text-label-quaternary">
          <X className="h-4 w-4" />
        </button>
      </div>
      <p className="text-caption-1 text-label-secondary mb-3">
        Campus “{report.campus.name}” deployed from the {report.template.campus_type} template
        {" "}({report.template.jurisdiction_used} · {report.template.region_used}).
      </p>
      <div className="space-y-2 mb-4">
        {report.steps.map((s) => (
          <div key={s.step} className="flex items-center justify-between gap-3 rounded-xl bg-bg-elevated px-4 py-2.5">
            <div className="min-w-0">
              <p className="text-callout font-semibold text-label-primary">{deployStepLabel(s.step)}</p>
              {s.detail && <p className="text-caption-1 text-label-tertiary">{s.detail}</p>}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <span className="text-caption-1 font-semibold text-label-secondary tabular-nums">{s.count}</span>
              <span
                className={cn(
                  "text-caption-1 font-semibold rounded-full px-2 py-0.5",
                  s.status === "created"
                    ? "text-green-400 bg-green-400/10"
                    : "text-label-secondary bg-chrome border border-separator/40",
                )}
              >
                {s.status === "created" ? "Created" : "Skipped"}
              </span>
            </div>
          </div>
        ))}
      </div>
      <button
        type="button"
        onClick={() => router.push(`/operations/${report.campus.id}`)}
        className="w-full py-3 rounded-xl bg-accent text-white font-semibold text-callout flex items-center justify-center gap-2 transition-all active:scale-[0.98]"
      >
        View Campus <ExternalLink className="h-4 w-4" />
      </button>
    </>
  );
}

function DeployCampusModal({
  project,
  onClose,
  onDeployed,
}: {
  project: QuillProject;
  onClose: () => void;
  onDeployed: (report: DeploymentReport) => void;
}) {
  const { data: catalog, isLoading: catalogLoading, error: catalogError } = useDeployTemplateCatalog();
  const deploy = useDeployCampusFromTemplate();
  const [name, setName] = React.useState(project.name);
  const [campusType, setCampusType] = React.useState("");
  const [jurisdiction, setJurisdiction] = React.useState("");
  const [region, setRegion] = React.useState("");

  // Default each select to the first catalog option once the catalog loads.
  React.useEffect(() => {
    if (!catalog) return;
    setCampusType((v) => v || (catalog.campus_types[0]?.key ?? ""));
    setJurisdiction((v) => v || (catalog.jurisdictions[0]?.key ?? ""));
    setRegion((v) => v || (catalog.regions[0]?.key ?? ""));
  }, [catalog]);

  const canSubmit = Boolean(name.trim() && campusType && jurisdiction && region) && !deploy.isPending;

  function handleDeploy() {
    if (!canSubmit) return;
    deploy.mutate(
      {
        project_id: project.id,
        name: name.trim(),
        campus_type: campusType,
        jurisdiction,
        region,
      },
      { onSuccess: (report) => onDeployed(report) },
    );
  }

  const selects = [
    { label: "Campus Type", value: campusType, set: setCampusType, options: catalog?.campus_types ?? [] },
    { label: "Jurisdiction", value: jurisdiction, set: setJurisdiction, options: catalog?.jurisdictions ?? [] },
    { label: "Region", value: region, set: setRegion, options: catalog?.regions ?? [] },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50" onClick={onClose}>
      <div
        className="w-full max-w-lg bg-chrome rounded-t-3xl p-6 pb-[calc(env(safe-area-inset-bottom)+24px)] max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="w-10 h-1 bg-separator/60 rounded-full mx-auto mb-4" />
        <p className="text-headline font-semibold text-label-primary mb-1">Deploy New Campus</p>
        <p className="text-caption-1 text-label-secondary mb-4">
          One-shot deployment from a standard template: campus, monitoring agents, equipment,
          compliance checklist, vendors, and dashboard seed.
        </p>

        {catalogLoading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 text-label-quaternary animate-spin" />
          </div>
        )}
        {catalogError != null && (
          <p className="text-callout text-red-400 text-center py-6">Failed to load template catalog.</p>
        )}

        {catalog && (
          <>
            <div className="space-y-3">
              <div>
                <label className="block text-footnote font-semibold text-label-secondary uppercase tracking-wide mb-1">
                  Campus Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Columbus Campus 1"
                  className="w-full rounded-xl px-4 py-2.5 text-body text-label-primary bg-bg-elevated border border-separator/60 placeholder:text-label-quaternary focus:outline-none focus:border-accent"
                />
              </div>
              {selects.map(({ label, value, set, options }) => (
                <div key={label}>
                  <label className="block text-footnote font-semibold text-label-secondary uppercase tracking-wide mb-1">
                    {label}
                  </label>
                  <select
                    value={value}
                    onChange={(e) => set(e.target.value)}
                    className="w-full rounded-xl px-4 py-2.5 text-body text-label-primary bg-bg-elevated border border-separator/60 focus:outline-none focus:border-accent appearance-none"
                  >
                    {options.map((o) => (
                      <option key={o.key} value={o.key}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
            </div>

            {deploy.isError && (
              <p className="text-caption-1 text-red-400 mt-3">{errorDetail(deploy.error)}</p>
            )}

            <div className="flex gap-3 mt-5">
              <button
                type="button"
                disabled={!canSubmit}
                onClick={handleDeploy}
                className="flex-1 py-3 rounded-xl bg-accent text-white font-semibold text-callout flex items-center justify-center gap-2 transition-all active:scale-[0.98] disabled:opacity-60"
              >
                {deploy.isPending ? (
                  <><Loader2 className="h-4 w-4 animate-spin" /> Deploying…</>
                ) : (
                  <><Zap className="h-4 w-4" /> Deploy Campus</>
                )}
              </button>
              <button
                type="button"
                onClick={onClose}
                className="flex-1 py-3 rounded-xl border border-separator/60 text-label-primary font-semibold text-callout"
              >
                Cancel
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── Go-Live (Project → Campus graduation, Sprint 5.1 + 5.4 template deploy) ────
function GoLiveSection({ project }: { project: QuillProject }) {
  const router = useRouter();
  const { data: campusList } = useCampusesByProject(project.id);
  const createCampus = useCreateCampus();
  const linkedCampus = campusList?.items?.[0];
  const [showDeployModal, setShowDeployModal] = React.useState(false);
  const [report, setReport] = React.useState<DeploymentReport | null>(null);

  // Only relevant once the project is commissioning, or after a campus exists.
  if (!linkedCampus && project.phase !== "commissioning" && !report) return null;

  return (
    <Card>
      {report ? (
        <DeploymentReportView report={report} onDismiss={() => setReport(null)} />
      ) : (
        <>
          <p className="text-callout font-semibold text-label-primary mb-2">Go Live</p>
          {linkedCampus ? (
            <button
              type="button"
              onClick={() => router.push(`/operations/${linkedCampus.id}`)}
              className="w-full flex items-center justify-between rounded-xl bg-accent/10 border border-accent/20 px-4 py-3"
            >
              <span className="text-callout font-semibold text-accent">
                Linked Campus: {linkedCampus.name}
              </span>
              <ExternalLink className="h-4 w-4 text-accent shrink-0" />
            </button>
          ) : (
            <>
              <p className="text-caption-1 text-label-secondary mb-3">
                This project is commissioning. Deploy a full campus from a standard template,
                or graduate it to a bare campus in Operations.
              </p>
              <button
                type="button"
                onClick={() => setShowDeployModal(true)}
                className={cn(
                  "w-full py-3 rounded-xl font-semibold text-callout mb-3",
                  "bg-accent text-white flex items-center justify-center gap-2",
                  "transition-all active:scale-[0.98]",
                )}
              >
                <Zap className="h-4 w-4" /> Deploy New Campus
              </button>
              <button
                type="button"
                disabled={createCampus.isPending}
                onClick={() =>
                  createCampus.mutate({
                    name: project.name,
                    project_id: project.id,
                    mw_capacity: 0,
                    status: "commissioning",
                  })
                }
                className={cn(
                  "w-full py-3 rounded-xl font-semibold text-callout",
                  "border border-separator/60 text-label-primary flex items-center justify-center gap-2",
                  "transition-all active:scale-[0.98]",
                  createCampus.isPending && "opacity-60 cursor-not-allowed",
                )}
              >
                {createCampus.isPending ? (
                  <><Loader2 className="h-4 w-4 animate-spin" /> Creating campus…</>
                ) : (
                  <>Go Live (bare campus)</>
                )}
              </button>
            </>
          )}
        </>
      )}
      {showDeployModal && (
        <DeployCampusModal
          project={project}
          onClose={() => setShowDeployModal(false)}
          onDeployed={(r) => {
            setReport(r);
            setShowDeployModal(false);
          }}
        />
      )}
    </Card>
  );
}

function OverviewTab({
  project,
  onAdvancePhase,
  advancing,
}: {
  project: QuillProject;
  onAdvancePhase: () => void;
  advancing: boolean;
}) {
  const { label: statusLabel, cls: statusCls } = statusBadge(project.status);
  const vb = verdictLabel(project.site_verdict);
  const router = useRouter();
  const currentPhaseIdx = phaseIndex(project.phase);
  const isLastPhase = currentPhaseIdx === PHASES.length - 1;

  return (
    <>
      {/* Header card */}
      <Card>
        <p className="text-headline font-bold text-label-primary mb-1">{project.name}</p>
        {project.address && (
          <div className="flex items-center gap-1 mb-3">
            <MapPin className="h-3.5 w-3.5 text-label-tertiary shrink-0" />
            <p className="text-callout text-label-secondary">{project.address}</p>
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <span className={cn("text-caption-1 font-semibold rounded-full px-2 py-0.5", statusCls)}>
            {statusLabel}
          </span>
          {project.workload_type && (
            <span className="text-caption-1 font-medium text-label-secondary bg-bg-elevated rounded-full px-2 py-0.5">
              {workloadLabel(project.workload_type)}
            </span>
          )}
        </div>

        {/* Site linkage */}
        {project.site_id && (
          <div className="mt-3 pt-3 border-t border-separator/30 flex items-center gap-3">
            <div className="flex-1">
              <p className="text-footnote text-label-tertiary">From Site Evaluation</p>
              <div className="flex items-center gap-2 mt-0.5">
                {project.site_score != null && (
                  <span className={cn("text-callout font-bold tabular-nums", scoreColor(project.site_score))}>
                    {project.site_score.toFixed(0)}/100
                  </span>
                )}
                {vb && (
                  <span className={cn("text-caption-1 font-semibold rounded-full px-2 py-0.5", vb.cls)}>
                    {vb.label}
                  </span>
                )}
              </div>
            </div>
            <button
              type="button"
              onClick={() => router.push(`/sites/${project.site_id}`)}
              className="flex items-center gap-1 text-accent text-caption-1 font-semibold"
            >
              View Site <ExternalLink className="h-3 w-3" />
            </button>
          </div>
        )}
      </Card>

      {/* Phase tracker */}
      <Card>
        <p className="text-callout font-semibold text-label-primary mb-4">Phase Tracker</p>
        <PhaseStepper phase={project.phase} />
        {!isLastPhase && (
          <button
            type="button"
            disabled={advancing}
            onClick={onAdvancePhase}
            className={cn(
              "mt-4 w-full py-3 rounded-xl font-semibold text-callout",
              "border border-accent text-accent",
              "flex items-center justify-center gap-2",
              "transition-all active:scale-[0.98]",
              advancing && "opacity-60 cursor-not-allowed",
            )}
          >
            {advancing ? (
              <><Loader2 className="h-4 w-4 animate-spin" /> Advancing…</>
            ) : (
              <>Advance to {PHASES[currentPhaseIdx + 1]?.label}<ChevronRight className="h-4 w-4" /></>
            )}
          </button>
        )}
        {isLastPhase && (
          <div className="mt-4 rounded-xl bg-accent/10 border border-accent/20 px-4 py-3 text-center">
            <p className="text-callout font-semibold text-accent">🎉 Project Complete</p>
            <p className="text-caption-1 text-label-secondary mt-0.5">This project has reached Turnover.</p>
          </div>
        )}
      </Card>

      {/* Go Live — Project → Campus graduation (Sprint 5.1) */}
      <GoLiveSection project={project} />

      {/* Budget */}
      <BudgetSection project={project} />

      {/* Notes */}
      <NotesSection project={project} />

      {/* Timestamps */}
      <div className="px-1 text-caption-1 text-label-quaternary space-y-1">
        <p>Created {new Date(project.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</p>
        <p>Updated {new Date(project.updated_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</p>
      </div>
    </>
  );
}

// ── Milestones Tab ────────────────────────────────────────────────────────────

function milestoneStatus(m: ProjectMilestone): "complete" | "overdue" | "upcoming" {
  if (m.completed_at) return "complete";
  if (m.due_date && new Date(m.due_date) < new Date()) return "overdue";
  return "upcoming";
}

function MilestonesTab({ projectId }: { projectId: string }) {
  const { data, isLoading } = useProjectMilestones(projectId);
  const milestones = data?.items ?? [];
  const createMilestone = useCreateMilestone(projectId);

  const [showForm, setShowForm] = React.useState(false);
  const [newName, setNewName] = React.useState("");
  const [newDate, setNewDate] = React.useState("");

  function handleCreate() {
    if (!newName.trim()) return;
    createMilestone.mutate(
      { name: newName.trim(), due_date: newDate || null },
      {
        onSuccess: () => {
          setNewName("");
          setNewDate("");
          setShowForm(false);
        },
      },
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-label-quaternary" />
      </div>
    );
  }

  return (
    <>
      {/* Add Milestone */}
      {!showForm ? (
        <button
          type="button"
          onClick={() => setShowForm(true)}
          className="w-full mb-4 py-2.5 rounded-xl border border-dashed border-accent/40 text-accent text-callout font-semibold flex items-center justify-center gap-2"
        >
          <Plus className="h-4 w-4" /> Add Milestone
        </button>
      ) : (
        <Card>
          <p className="text-callout font-semibold text-label-primary mb-3">New Milestone</p>
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Milestone name"
            className="w-full rounded-xl px-4 py-2.5 mb-3 text-body text-label-primary bg-bg-elevated border border-separator/60 placeholder:text-label-quaternary focus:outline-none focus:border-accent"
          />
          <div className="mb-3">
            <label className="block text-footnote font-semibold text-label-secondary uppercase tracking-wide mb-1">Due Date (optional)</label>
            <input
              type="date"
              value={newDate}
              onChange={(e) => setNewDate(e.target.value)}
              className="w-full rounded-xl px-4 py-2.5 text-body text-label-primary bg-bg-elevated border border-separator/60 focus:outline-none focus:border-accent"
            />
          </div>
          <div className="flex gap-3">
            <button
              type="button"
              disabled={!newName.trim() || createMilestone.isPending}
              onClick={handleCreate}
              className="flex-1 py-2.5 rounded-xl bg-accent text-white font-semibold text-callout disabled:opacity-60"
            >
              {createMilestone.isPending ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              onClick={() => { setShowForm(false); setNewName(""); setNewDate(""); }}
              className="flex-1 py-2.5 rounded-xl border border-separator/60 text-label-primary font-semibold text-callout"
            >
              Cancel
            </button>
          </div>
        </Card>
      )}

      {milestones.length === 0 && !showForm && (
        <div className="text-center py-8 text-label-quaternary text-callout">No milestones yet.</div>
      )}

      {milestones.map((m) => (
        <MilestoneRow key={m.id} milestone={m} projectId={projectId} />
      ))}
    </>
  );
}

function MilestoneRow({ milestone: m, projectId }: { milestone: ProjectMilestone; projectId: string }) {
  const st = milestoneStatus(m);
  const updateMilestone = useUpdateMilestone(projectId, m.id);
  const deleteMilestone = useDeleteMilestone(projectId);

  function toggleComplete() {
    updateMilestone.mutate({ completed: st !== "complete" });
  }

  return (
    <div
      className={cn(
        "rounded-2xl border p-4 mb-3 flex items-start gap-3",
        st === "overdue"
          ? "bg-red-500/5 border-red-500/20"
          : "bg-chrome/80 border-separator/40",
      )}
    >
      {/* Checkbox */}
      <button
        type="button"
        onClick={toggleComplete}
        disabled={updateMilestone.isPending}
        className={cn(
          "mt-0.5 w-5 h-5 rounded-full border-2 flex items-center justify-center shrink-0 transition-colors",
          st === "complete"
            ? "border-accent bg-accent"
            : st === "overdue"
              ? "border-red-400"
              : "border-separator/60",
        )}
      >
        {st === "complete" && <span className="text-white text-caption-2">✓</span>}
      </button>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <p className={cn(
          "text-callout font-semibold",
          st === "complete" ? "line-through text-label-quaternary" : "text-label-primary",
        )}>
          {m.name}
        </p>
        {m.due_date && (
          <p className={cn("text-caption-1 mt-0.5", st === "overdue" ? "text-red-400 font-semibold" : "text-label-tertiary")}>
            Due {new Date(m.due_date).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
            {st === "overdue" && " · Overdue"}
          </p>
        )}
        {m.completed_at && (
          <p className="text-caption-1 mt-0.5 text-green-400">
            Completed {new Date(m.completed_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
          </p>
        )}
      </div>

      {/* Delete */}
      <button
        type="button"
        onClick={() => deleteMilestone.mutate(m.id)}
        disabled={deleteMilestone.isPending}
        className="text-label-quaternary hover:text-red-400 transition-colors shrink-0"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

// ── Log Tab ───────────────────────────────────────────────────────────────────

const LOG_TYPE_CONFIG: Record<string, { label: string; cls: string }> = {
  general: { label: "General", cls: "text-label-secondary bg-bg-elevated" },
  issue: { label: "Issue", cls: "text-red-400 bg-red-400/10" },
  decision: { label: "Decision", cls: "text-blue-400 bg-blue-400/10" },
  milestone: { label: "Milestone", cls: "text-green-400 bg-green-400/10" },
};

function logTypeCfg(type: string) {
  return LOG_TYPE_CONFIG[type] ?? { label: type, cls: "text-label-secondary bg-bg-elevated" };
}

function LogTab({ projectId }: { projectId: string }) {
  const { data, isLoading } = useProjectLog(projectId);
  const entries = data?.items ?? [];
  const addEntry = useAddLogEntry(projectId);

  const [showForm, setShowForm] = React.useState(false);
  const [text, setText] = React.useState("");
  const [entryType, setEntryType] = React.useState("general");

  function handleAdd() {
    if (!text.trim()) return;
    addEntry.mutate(
      { text: text.trim(), entry_type: entryType },
      {
        onSuccess: () => {
          setText("");
          setEntryType("general");
          setShowForm(false);
        },
      },
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-label-quaternary" />
      </div>
    );
  }

  return (
    <>
      {!showForm ? (
        <button
          type="button"
          onClick={() => setShowForm(true)}
          className="w-full mb-4 py-2.5 rounded-xl border border-dashed border-accent/40 text-accent text-callout font-semibold flex items-center justify-center gap-2"
        >
          <Plus className="h-4 w-4" /> Add Entry
        </button>
      ) : (
        <Card>
          <p className="text-callout font-semibold text-label-primary mb-3">New Log Entry</p>
          <div className="mb-3">
            <label className="block text-footnote font-semibold text-label-secondary uppercase tracking-wide mb-1">Type</label>
            <div className="flex gap-2 flex-wrap">
              {["general", "issue", "decision", "milestone"].map((t) => {
                const cfg = logTypeCfg(t);
                return (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setEntryType(t)}
                    className={cn(
                      "text-caption-1 font-semibold rounded-full px-3 py-1 border transition-colors",
                      entryType === t
                        ? `${cfg.cls} border-transparent`
                        : "border-separator/40 text-label-secondary",
                    )}
                  >
                    {cfg.label}
                  </button>
                );
              })}
            </div>
          </div>
          <textarea
            autoFocus
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={3}
            placeholder="What happened? What was decided?"
            className="w-full rounded-xl px-4 py-3 mb-3 text-body text-label-primary bg-bg-elevated border border-separator/60 placeholder:text-label-quaternary focus:outline-none focus:border-accent resize-none"
          />
          <div className="flex gap-3">
            <button
              type="button"
              disabled={!text.trim() || addEntry.isPending}
              onClick={handleAdd}
              className="flex-1 py-2.5 rounded-xl bg-accent text-white font-semibold text-callout disabled:opacity-60"
            >
              {addEntry.isPending ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              onClick={() => { setShowForm(false); setText(""); setEntryType("general"); }}
              className="flex-1 py-2.5 rounded-xl border border-separator/60 text-label-primary font-semibold text-callout"
            >
              Cancel
            </button>
          </div>
        </Card>
      )}

      {entries.length === 0 && !showForm && (
        <div className="text-center py-8 text-label-quaternary text-callout">No log entries yet.</div>
      )}

      <div className="space-y-2">
        {entries.map((entry) => {
          const cfg = logTypeCfg(entry.entry_type);
          return (
            <div key={entry.id} className="rounded-xl bg-chrome/80 border border-separator/40 px-4 py-3">
              <div className="flex items-center gap-2 mb-1">
                <span className={cn("text-caption-2 font-semibold rounded-full px-2 py-0.5", cfg.cls)}>
                  {cfg.label}
                </span>
                <span className="text-caption-2 text-label-quaternary">
                  {new Date(entry.created_at).toLocaleDateString("en-US", {
                    month: "short", day: "numeric", year: "numeric",
                    hour: "2-digit", minute: "2-digit",
                  })}
                </span>
              </div>
              <p className="text-callout text-label-secondary leading-relaxed">{entry.text}</p>
            </div>
          );
        })}
      </div>
    </>
  );
}

// ── Links Tab ─────────────────────────────────────────────────────────────────

function LinksTab({ projectId }: { projectId: string }) {
  const { data: docLinks } = useProjectDocumentLinks(projectId);
  const { data: contractLinks } = useProjectContractLinks(projectId);
  const { data: estimateLinks } = useProjectEstimateLinks(projectId);

  const { data: contractsData } = useContractsList();
  const { data: estimatesData } = useListEstimates();
  const contractItems = (contractsData as any)?.items ?? [];
  const estimateItems = (estimatesData as any)?.items ?? [];

  const addDocLink = useAddDocumentLink(projectId);
  const linkContract = useLinkContract(projectId);
  const linkEstimate = useLinkEstimate(projectId);

  const [showDocForm, setShowDocForm] = React.useState(false);
  const [docName, setDocName] = React.useState("");
  const [docUrl, setDocUrl] = React.useState("");

  const [showContractModal, setShowContractModal] = React.useState(false);
  const [showEstimateModal, setShowEstimateModal] = React.useState(false);

  const router = useRouter();

  function handleAddDoc() {
    if (!docName.trim()) return;
    addDocLink.mutate(
      { name: docName.trim(), url: docUrl.trim() || null },
      { onSuccess: () => { setDocName(""); setDocUrl(""); setShowDocForm(false); } },
    );
  }

  return (
    <div className="space-y-2">
      {/* Documents section */}
      <div className="mb-2">
        <div className="flex items-center justify-between mb-2">
          <p className="text-footnote font-semibold text-label-tertiary uppercase tracking-wide">Documents</p>
          <button type="button" onClick={() => setShowDocForm(true)} className="text-accent text-callout flex items-center gap-1">
            <Plus className="h-3.5 w-3.5" /> Add
          </button>
        </div>

        {showDocForm && (
          <Card>
            <input
              autoFocus
              value={docName}
              onChange={(e) => setDocName(e.target.value)}
              placeholder="Document name"
              className="w-full rounded-xl px-4 py-2.5 mb-3 text-body text-label-primary bg-bg-elevated border border-separator/60 placeholder:text-label-quaternary focus:outline-none focus:border-accent"
            />
            <input
              value={docUrl}
              onChange={(e) => setDocUrl(e.target.value)}
              placeholder="URL (optional)"
              className="w-full rounded-xl px-4 py-2.5 mb-3 text-body text-label-primary bg-bg-elevated border border-separator/60 placeholder:text-label-quaternary focus:outline-none focus:border-accent"
            />
            <div className="flex gap-3">
              <button
                type="button"
                disabled={!docName.trim() || addDocLink.isPending}
                onClick={handleAddDoc}
                className="flex-1 py-2.5 rounded-xl bg-accent text-white font-semibold text-callout disabled:opacity-60"
              >
                {addDocLink.isPending ? "Saving…" : "Save"}
              </button>
              <button type="button" onClick={() => setShowDocForm(false)} className="flex-1 py-2.5 rounded-xl border border-separator/60 text-label-primary font-semibold text-callout">
                Cancel
              </button>
            </div>
          </Card>
        )}

        {(docLinks?.items ?? []).map((dl) => (
          <div key={dl.id} className="rounded-xl bg-chrome/80 border border-separator/40 px-4 py-3 mb-2 flex items-center gap-3">
            <FileText className="h-4 w-4 text-label-tertiary shrink-0" />
            <span className="flex-1 text-callout text-label-primary truncate">{dl.name}</span>
            {dl.url && (
              <a href={dl.url} target="_blank" rel="noopener noreferrer" className="text-accent shrink-0">
                <ExternalLink className="h-4 w-4" />
              </a>
            )}
            {dl.document_id && (
              <button type="button" onClick={() => router.push(`/documents/${dl.document_id}`)} className="text-accent shrink-0">
                <ExternalLink className="h-4 w-4" />
              </button>
            )}
          </div>
        ))}
        {(docLinks?.items ?? []).length === 0 && !showDocForm && (
          <p className="text-caption-1 text-label-quaternary px-1 mb-3">No documents linked.</p>
        )}
      </div>

      {/* Contracts section */}
      <div className="mb-2">
        <div className="flex items-center justify-between mb-2">
          <p className="text-footnote font-semibold text-label-tertiary uppercase tracking-wide">Contracts</p>
          <button type="button" onClick={() => setShowContractModal(true)} className="text-accent text-callout flex items-center gap-1">
            <Plus className="h-3.5 w-3.5" /> Link
          </button>
        </div>
        {(contractLinks?.items ?? []).map((cl) => {
          const contract = contractItems.find((c: any) => c.upload_id === cl.contract_id);
          return (
            <div key={cl.id} className="rounded-xl bg-chrome/80 border border-separator/40 px-4 py-3 mb-2 flex items-center gap-3">
              <FileText className="h-4 w-4 text-label-tertiary shrink-0" />
              <span className="flex-1 text-callout text-label-primary truncate">
                {contract?.project_label || cl.contract_id.slice(0, 12) + "…"}
              </span>
              <button type="button" onClick={() => router.push(`/contracts/${cl.contract_id}`)} className="text-accent shrink-0">
                <ExternalLink className="h-4 w-4" />
              </button>
            </div>
          );
        })}
        {(contractLinks?.items ?? []).length === 0 && (
          <p className="text-caption-1 text-label-quaternary px-1 mb-3">No contracts linked.</p>
        )}
      </div>

      {/* Estimates section */}
      <div className="mb-2">
        <div className="flex items-center justify-between mb-2">
          <p className="text-footnote font-semibold text-label-tertiary uppercase tracking-wide">Estimates</p>
          <button type="button" onClick={() => setShowEstimateModal(true)} className="text-accent text-callout flex items-center gap-1">
            <Plus className="h-3.5 w-3.5" /> Link
          </button>
        </div>
        {(estimateLinks?.items ?? []).map((el) => {
          const estimate = estimateItems.find((e: any) => e.upload_id === el.estimate_id);
          return (
            <div key={el.id} className="rounded-xl bg-chrome/80 border border-separator/40 px-4 py-3 mb-2 flex items-center gap-3">
              <DollarSign className="h-4 w-4 text-label-tertiary shrink-0" />
              <span className="flex-1 text-callout text-label-primary truncate">
                {estimate?.project_label || el.estimate_id.slice(0, 12) + "…"}
              </span>
              <button type="button" onClick={() => router.push(`/estimates/${el.estimate_id}`)} className="text-accent shrink-0">
                <ExternalLink className="h-4 w-4" />
              </button>
            </div>
          );
        })}
        {(estimateLinks?.items ?? []).length === 0 && (
          <p className="text-caption-1 text-label-quaternary px-1 mb-3">No estimates linked.</p>
        )}
      </div>

      {/* Contract picker modal */}
      {showContractModal && (
        <LinkPickerModal
          title="Link Contract"
          items={contractItems.map((c: any) => ({
            id: c.upload_id,
            label: c.project_label || c.upload_id.slice(0, 12) + "…",
            sub: c.contract_type ?? c.status,
          }))}
          alreadyLinked={(contractLinks?.items ?? []).map((cl) => cl.contract_id)}
          onSelect={(id) => {
            linkContract.mutate({ contract_id: id }, { onSuccess: () => setShowContractModal(false) });
          }}
          onClose={() => setShowContractModal(false)}
          pending={linkContract.isPending}
        />
      )}

      {/* Estimate picker modal */}
      {showEstimateModal && (
        <LinkPickerModal
          title="Link Estimate"
          items={estimateItems.map((e: any) => ({
            id: e.upload_id,
            label: e.project_label || e.upload_id.slice(0, 12) + "…",
            sub: e.status,
          }))}
          alreadyLinked={(estimateLinks?.items ?? []).map((el) => el.estimate_id)}
          onSelect={(id) => {
            linkEstimate.mutate({ estimate_id: id }, { onSuccess: () => setShowEstimateModal(false) });
          }}
          onClose={() => setShowEstimateModal(false)}
          pending={linkEstimate.isPending}
        />
      )}
    </div>
  );
}

function LinkPickerModal({
  title,
  items,
  alreadyLinked,
  onSelect,
  onClose,
  pending,
}: {
  title: string;
  items: { id: string; label: string; sub?: string }[];
  alreadyLinked: string[];
  onSelect: (id: string) => void;
  onClose: () => void;
  pending: boolean;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50" onClick={onClose}>
      <div
        className="w-full max-w-lg bg-chrome rounded-t-3xl p-6 pb-[calc(env(safe-area-inset-bottom)+24px)] max-h-[70vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="w-10 h-1 bg-separator/60 rounded-full mx-auto mb-4" />
        <p className="text-headline font-semibold text-label-primary mb-4">{title}</p>
        {items.length === 0 && (
          <p className="text-callout text-label-quaternary text-center py-6">Nothing available to link.</p>
        )}
        {items.map((item) => {
          const linked = alreadyLinked.includes(item.id);
          return (
            <button
              key={item.id}
              type="button"
              disabled={linked || pending}
              onClick={() => onSelect(item.id)}
              className={cn(
                "w-full text-left rounded-xl px-4 py-3 mb-2 border flex items-center justify-between",
                linked
                  ? "border-separator/20 opacity-40 cursor-default"
                  : "border-separator/40 bg-bg-elevated hover:border-accent/40 transition-colors",
              )}
            >
              <div>
                <p className="text-callout font-semibold text-label-primary">{item.label}</p>
                {item.sub && <p className="text-caption-1 text-label-tertiary">{item.sub}</p>}
              </div>
              {linked && <span className="text-caption-1 text-label-quaternary">Already linked</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ProjectDetailPage() {
  const router = useRouter();
  const params = useParams();
  const projectId = params.id as string;

  const { data: project, isLoading, error } = useProject(projectId);
  const updateProject = useUpdateProject();

  const [activeTab, setActiveTab] = React.useState<TabValue>("overview");

  if (isLoading) {
    return (
      <MobileShell>
        <TopBar
          title="Project"
          left={
            <button type="button" onClick={() => router.back()} className="text-accent font-semibold text-callout flex items-center gap-1">
              <ArrowLeft className="h-4 w-4" /> Projects
            </button>
          }
        />
        <div className="flex items-center justify-center pt-24">
          <Loader2 className="h-8 w-8 text-label-quaternary animate-spin" />
        </div>
      </MobileShell>
    );
  }

  if (error || !project) {
    return (
      <MobileShell>
        <TopBar
          title="Project"
          left={
            <button type="button" onClick={() => router.back()} className="text-accent font-semibold text-callout flex items-center gap-1">
              <ArrowLeft className="h-4 w-4" /> Projects
            </button>
          }
        />
        <div className="px-4 pt-6 text-center text-label-secondary">
          {error ? "Failed to load project." : "Project not found."}
        </div>
      </MobileShell>
    );
  }

  function handleAdvancePhase() {
    updateProject.mutate({ id: project!.id, body: { advance_phase: true } });
  }

  return (
    <MobileShell>
      <TopBar
        title={project.name}
        left={
          <button
            type="button"
            onClick={() => router.back()}
            className="text-accent font-semibold text-callout flex items-center gap-1"
          >
            <ArrowLeft className="h-4 w-4" /> Projects
          </button>
        }
      />

      {/* Tab selector */}
      <div className="px-4 pt-3 pb-2">
        <SegmentedControl
          options={TABS}
          value={activeTab}
          onChange={(v) => setActiveTab(v as TabValue)}
        />
      </div>

      {/* Tab content */}
      <div className="px-4 pb-12">
        {activeTab === "overview" && (
          <OverviewTab
            project={project}
            onAdvancePhase={handleAdvancePhase}
            advancing={updateProject.isPending}
          />
        )}
        {activeTab === "milestones" && <MilestonesTab projectId={projectId} />}
        {activeTab === "log" && <LogTab projectId={projectId} />}
        {activeTab === "links" && <LinksTab projectId={projectId} />}
      </div>
    </MobileShell>
  );
}
