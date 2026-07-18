"use client";

/**
 * /sites/[id] — Site Detail page
 *
 * Visual layer ported from quill-platform-builder/src/routes/sites.$id.tsx.
 * Data wired to prod hooks from @/lib/api:
 *   - useSite(id)            → Site | undefined
 *   - useSiteAdvanceStatus() → { status, project_id, ... }
 *   - useSiteDriveIntake()   → DriveIntake | undefined
 *   - useRunSiteEvaluation() → mutation
 *   - useAdvanceSite()       → mutation
 *
 * NOTE: Lovable's sites.$id.tsx references site.notes, site.advance_status,
 * site.project_id, and site.drive_intake as direct Site fields — these do NOT
 * exist on prod's SiteSchema. Prod handles advance state via useSiteAdvanceStatus()
 * and drive intake via useSiteDriveIntake(). That wiring is preserved here.
 * A "Notes" card is omitted since prod's SiteSchema has no top-level notes field.
 */

import * as React from "react";
import { useRouter, useParams } from "next/navigation";
import { toast } from "sonner";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronRight,
  Clock,
  FileText,
  FolderKanban,
  Loader2,
  Play,
  XCircle,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { ModuleAgentBar } from "@/components/journey/ModuleAgentBar";
import { Scorecard } from "@/components/sites/Scorecard";
import {
  siteAddress,
  verdictInfo,
  workloadLabel,
  scoreColor,
} from "@/components/sites/SiteCard";
import {
  useSite,
  useRunSiteEvaluation,
  useAdvanceSite,
  useSiteAdvanceStatus,
  useSiteDriveIntake,
  type DriveIntakeDocument,
} from "@/lib/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

function statusBadge(status: string): { label: string; cls: string } {
  switch (status) {
    case "intake":      return { label: "Intake",       cls: "text-label-secondary bg-bg-elevated" };
    case "researching": return { label: "Researching",  cls: "text-info bg-info/10" };
    case "scoring":     return { label: "Scoring",      cls: "text-accent bg-accent/10" };
    case "review":      return { label: "Review",       cls: "text-warning bg-warning/10" };
    case "decided":     return { label: "Decided",      cls: "text-success bg-success/10" };
    default:            return { label: status,         cls: "text-label-secondary bg-bg-elevated" };
  }
}

function scoreBarColor(score: number): string {
  if (score >= 70) return "bg-success";
  if (score >= 50) return "bg-warning";
  return "bg-danger";
}

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("glass mb-4 rounded-2xl border border-hairline p-5", className)}>
      {children}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SiteDetailPage() {
  const router = useRouter();
  const params = useParams();
  const siteId = params.id as string;

  const { data: site, isLoading, error } = useSite(siteId);
  const runEvaluation = useRunSiteEvaluation();
  const { data: advanceStatus } = useSiteAdvanceStatus(siteId);
  const { data: driveIntake } = useSiteDriveIntake(siteId);
  const advanceSite = useAdvanceSite();

  const backBtn = (
    <button
      type="button"
      onClick={() => router.back()}
      className="text-callout flex items-center gap-1 font-semibold text-accent"
    >
      <ArrowLeft className="h-4 w-4" /> Sites
    </button>
  );

  if (isLoading) {
    return (
      <MobileShell>
        <TopBar title="Site" left={backBtn} />
        <div className="flex items-center justify-center pt-24">
          <Loader2 className="h-8 w-8 animate-spin text-label-quaternary" />
        </div>
      </MobileShell>
    );
  }

  if (error || !site) {
    return (
      <MobileShell>
        <TopBar title="Site" left={backBtn} />
        <div className="px-4 pt-6 text-center text-label-secondary">
          {error ? "Failed to load site." : "Site not found."}
        </div>
      </MobileShell>
    );
  }

  const total = site.scores?.total_weighted;
  const verdict = site.recommendation?.verdict;
  const status = statusBadge(site.status);
  const v = verdictInfo(verdict);
  const address = siteAddress(site);
  const canRun = site.status === "intake";
  const canAdvance = verdict === "strong_recommend" || verdict === "conditional";
  const advState = advanceStatus?.status ?? "none";
  const docs = site.documents ?? [];

  return (
    <MobileShell>
      <TopBar title={address.split(",")[0]} left={backBtn} />
      <ModuleAgentBar moduleKey="sites" />

      <div className="mx-auto w-full max-w-[708px] px-4 pt-3 pb-12 md:max-w-4xl md:px-8">
        {/* Hero — score + verdict + status */}
        <Card>
          <div className="mb-3 flex items-start justify-between">
            <div>
              <p className="text-callout mb-1 font-medium text-label-secondary">{address}</p>
              <div className="flex flex-wrap gap-2">
                <span className={cn("text-caption-1 rounded-full px-2 py-0.5 font-semibold", status.cls)}>
                  {status.label}
                </span>
                {site.target_workload && (
                  <span className="text-caption-1 rounded-full bg-bg-elevated px-2 py-0.5 font-medium text-label-secondary border border-hairline">
                    {workloadLabel(site.target_workload)}
                  </span>
                )}
                {site.target_mw != null && (
                  <span className="text-caption-1 flex items-center gap-0.5 text-label-secondary">
                    <Zap className="h-3 w-3 text-warning" /> {site.target_mw} MW
                  </span>
                )}
              </div>
            </div>
            {total != null && (
              <div className="ml-4 text-right">
                <p className={cn("text-large-title font-bold tabular-nums", scoreColor(total))}>
                  {total.toFixed(0)}
                </p>
                <p className="text-caption-1 text-label-tertiary">/100</p>
              </div>
            )}
          </div>

          {/* Score bar */}
          {total != null && (
            <div className="mb-3 h-2 overflow-hidden rounded-full bg-bg-elevated">
              <div
                className={cn("h-full rounded-full transition-all", scoreBarColor(total))}
                style={{ width: `${Math.min(100, total)}%` }}
              />
            </div>
          )}

          {/* Verdict */}
          {verdict && (
            <div className="flex items-center justify-between">
              <span className="text-footnote text-label-secondary">Verdict</span>
              <span className={cn("text-callout rounded-full px-3 py-1 font-semibold", v.cls)}>
                {v.label}
              </span>
            </div>
          )}
        </Card>

        {/* Recommendation */}
        {site.recommendation?.summary && (
          <Card>
            <p className="text-callout mb-2 font-semibold text-label-primary">Recommendation</p>
            <p className="text-callout leading-relaxed text-label-secondary">
              {site.recommendation.summary}
            </p>
            {(site.recommendation.strengths?.length ?? 0) > 0 && (
              <div className="mt-3">
                <p className="text-footnote mb-1.5 font-semibold text-success">Strengths</p>
                <ul className="space-y-1">
                  {site.recommendation.strengths!.map((s, i) => (
                    <li key={i} className="text-caption-1 flex gap-2 text-label-secondary">
                      <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />
                      <span>{s}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {(site.recommendation.risks?.length ?? 0) > 0 && (
              <div className="mt-3">
                <p className="text-footnote mb-1.5 font-semibold text-warning">Risks</p>
                <ul className="space-y-1">
                  {site.recommendation.risks!.map((r, i) => (
                    <li key={i} className="text-caption-1 flex gap-2 text-label-secondary">
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
                      <span>{r}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Card>
        )}

        {/* Scorecard */}
        {site.scores && (
          <div className="mb-4">
            <Scorecard site={site} />
          </div>
        )}

        {/* Drive Intake */}
        {driveIntake && driveIntake.status !== "none" && (
          <DriveIntakeCard intake={driveIntake} />
        )}

        {/* Documents */}
        {docs.length > 0 && (
          <Card>
            <p className="text-callout mb-3 font-semibold text-label-primary">Documents</p>
            <div className="space-y-2">
              {docs.map((doc) => (
                <div key={doc.doc_id} className="flex items-center gap-3 rounded-xl bg-bg-elevated p-3">
                  <FileText className="h-4 w-4 shrink-0 text-label-tertiary" />
                  <span className="text-callout truncate text-label-primary">
                    {doc.filename ?? doc.doc_id}
                  </span>
                  {doc.type && (
                    <span className="text-caption-1 ml-auto shrink-0 text-label-tertiary">
                      {doc.type}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* Actions */}
        <div className="space-y-3">
          {canRun && (
            <button
              type="button"
              disabled={runEvaluation.isPending}
              onClick={() =>
                runEvaluation.mutate(siteId, {
                  onSuccess: () =>
                    toast.success("Evaluation complete", {
                      description: "The scorecard has been updated.",
                    }),
                  onError: (err) =>
                    toast.error("Evaluation failed", {
                      description:
                        err instanceof Error ? err.message : "Please try again.",
                    }),
                })
              }
              className={cn(
                "text-body w-full rounded-2xl border border-accent py-3.5 font-semibold text-accent",
                "flex items-center justify-center gap-2 transition-all active:scale-[0.98]",
                runEvaluation.isPending && "cursor-not-allowed opacity-60",
              )}
            >
              {runEvaluation.isPending ? (
                <><Loader2 className="h-4 w-4 animate-spin" /> Running…</>
              ) : (
                <><Play className="h-4 w-4" /> Run Evaluation</>
              )}
            </button>
          )}

          {/* Advance flow — Lane-2 gated: request → pending approval → advanced */}
          {advState === "advanced" && advanceStatus?.project_id ? (
            <button
              type="button"
              onClick={() => router.push(`/projects/${advanceStatus.project_id}`)}
              className={cn(
                "text-body w-full rounded-2xl border border-success/30 bg-success/15 py-3.5 font-semibold text-success",
                "flex items-center justify-center gap-2 transition-all active:scale-[0.98]",
              )}
            >
              <CheckCircle2 className="h-4 w-4" /> Advanced — View Project
              <ChevronRight className="h-4 w-4" />
            </button>
          ) : advState === "pending_approval" ? (
            <button
              type="button"
              onClick={() => router.push("/queue")}
              className={cn(
                "text-body w-full rounded-2xl border border-warning/30 bg-warning/10 py-3.5 font-semibold text-warning",
                "flex items-center justify-center gap-2 transition-all active:scale-[0.98]",
              )}
            >
              <Clock className="h-4 w-4" /> Advance Pending Approval
              <ChevronRight className="h-4 w-4" />
            </button>
          ) : canAdvance ? (
            <button
              type="button"
              disabled={advanceSite.isPending}
              onClick={() => advanceSite.mutate(siteId)}
              className={cn(
                "text-body w-full rounded-2xl bg-accent py-3.5 font-semibold text-white",
                "flex items-center justify-center gap-2 transition-all active:scale-[0.98]",
                advanceSite.isPending && "cursor-not-allowed opacity-60",
              )}
            >
              {advanceSite.isPending ? (
                <><Loader2 className="h-4 w-4 animate-spin" /> Requesting Approval…</>
              ) : (
                <><FolderKanban className="h-4 w-4" /> Advance to Project</>
              )}
            </button>
          ) : null}
          {advanceSite.isError && (
            <p className="text-caption-1 text-center text-danger">
              {advanceSite.error?.message ?? "Advance request failed."}
            </p>
          )}
        </div>
      </div>
    </MobileShell>
  );
}

// ── Drive Intake Card ─────────────────────────────────────────────────────────

type DriveIntake = {
  site_id: string;
  status: "none" | "completed" | "completed_with_errors" | "failed";
  error?: string | null;
  documents: DriveIntakeDocument[];
};

function DriveIntakeCard({ intake }: { intake: DriveIntake }) {
  const pillCls =
    intake.status === "completed"
      ? "text-success bg-success/10"
      : intake.status === "completed_with_errors"
        ? "text-warning bg-warning/10"
        : "text-danger bg-danger/10";
  const pillLabel =
    intake.status === "completed"
      ? "Completed"
      : intake.status === "completed_with_errors"
        ? "Partial"
        : "Failed";

  return (
    <div className={cn("glass mb-4 rounded-2xl border border-hairline p-5")}>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-callout font-semibold text-label-primary">Drive Intake</p>
        <span className={cn("text-caption-1 rounded-full px-2 py-0.5 font-semibold", pillCls)}>
          {pillLabel}
        </span>
      </div>
      {intake.error && <p className="text-caption-1 mb-2 text-danger">{intake.error}</p>}
      {intake.documents.length === 0 && intake.status === "failed" && (
        <p className="text-caption-1 text-label-tertiary">
          No documents were imported from the Drive folder.
        </p>
      )}
      <div className="space-y-2">
        {intake.documents.map((d, i) => (
          <div key={d.file_id ?? i} className="flex items-start gap-3 rounded-xl bg-bg-elevated p-3">
            <IntakeStatusIcon status={d.status} />
            <div className="min-w-0 flex-1">
              <p className="text-callout truncate text-label-primary">{d.filename}</p>
              {d.detail && <p className="text-caption-1 text-label-tertiary">{d.detail}</p>}
            </div>
            <span className="text-caption-1 shrink-0 capitalize text-label-tertiary">{d.status}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function IntakeStatusIcon({ status }: { status: DriveIntakeDocument["status"] }) {
  switch (status) {
    case "indexed":
      return <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />;
    case "uploaded":
      return <Clock className="mt-0.5 h-4 w-4 shrink-0 text-info" />;
    case "skipped":
      return <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />;
    case "failed":
      return <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />;
    default:
      return <FileText className="mt-0.5 h-4 w-4 shrink-0 text-label-tertiary" />;
  }
}
