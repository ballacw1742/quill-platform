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
  useDecideSite,
  useDeleteSite,
  useUpdateSite,
  useUploadSiteDocuments,
  useSiteAdvanceStatus,
  useSiteDriveIntake,
  type DriveIntakeDocument,
} from "@/lib/api";
import { Trash2, Pencil, Upload } from "lucide-react";

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
  const decideSite = useDecideSite();
  const deleteSite = useDeleteSite();
  const updateSite = useUpdateSite();
  const uploadDocs = useUploadSiteDocuments();
  const [confirmDelete, setConfirmDelete] = React.useState(false);
  const [editing, setEditing] = React.useState(false);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

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
  const isRunning =
    site.status === "researching" ||
    site.status === "scoring" ||
    site.status === "intake_processing";
  const advState = advanceStatus?.status ?? "none";
  const docs = site.documents ?? [];

  // Human-in-the-loop decision state. A site is "evaluated" once it's past the
  // scoring pipeline (status review/scored/decided or it has a score/verdict).
  // Regardless of the AI verdict — even a low/"weak" score — a human must accept
  // or reject to move the site forward. This is intentionally NOT gated on
  // verdict === strong/conditional (that gate previously hid the action entirely
  // for weak sites, leaving no way to accept or reject).
  const finalVerdict = site.decision?.final_verdict ?? null; // "accepted" | "rejected" | null
  const isRejected = finalVerdict === "rejected";
  // A rejected site is read-only. Any other non-in-flight site can be re-scored
  // and its inputs edited — site development is additive (add files, refine
  // inputs, re-score; the ranking updates as the picture fills in).
  const canEdit = !isRejected && !isRunning;
  const hasBeenEvaluated = total != null || !!verdict || site.status === "decided";
  const canRun = !isRejected && !isRunning;
  const runLabel =
    site.status === "error"
      ? "Retry Evaluation"
      : hasBeenEvaluated
        ? "Re-score Evaluation"
        : "Run Evaluation";
  const isEvaluated =
    !canRun &&
    (total != null ||
      !!verdict ||
      ["review", "scoring", "scored", "decided"].includes(site.status));
  const isDecided = finalVerdict === "accepted" || finalVerdict === "rejected";
  const isAdvanced = advState === "advanced";
  const advancePending = advState === "pending_approval";

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

        {/* Edit inputs + add files (additive site development) — non-rejected only */}
        {canEdit && (
          <Card>
            <div className="mb-3 flex items-center justify-between">
              <p className="text-callout font-semibold text-label-primary">
                Inputs &amp; documents
              </p>
              {!editing && (
                <button
                  type="button"
                  onClick={() => setEditing(true)}
                  className="text-caption-1 flex items-center gap-1 font-semibold text-accent"
                >
                  <Pencil className="h-3.5 w-3.5" /> Edit
                </button>
              )}
            </div>

            {!editing ? (
              <>
                <p className="text-caption-1 text-label-tertiary">
                  Sites develop over time. Add documents or refine the inputs, then
                  re-score — the ranking updates as the picture fills in.
                </p>
                {/* Add files */}
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  className="hidden"
                  onChange={(e) => {
                    const files = Array.from(e.target.files ?? []);
                    if (files.length === 0) return;
                    uploadDocs.mutate(
                      { siteId, files },
                      {
                        onSuccess: (r) =>
                          toast.success(
                            `Added ${r.documents?.length ?? files.length} file(s)`,
                            { description: "Re-score to factor them in." },
                          ),
                        onError: (err) =>
                          toast.error("Upload failed", {
                            description:
                              err instanceof Error ? err.message : "Please try again.",
                          }),
                      },
                    );
                    e.target.value = "";
                  }}
                />
                <button
                  type="button"
                  disabled={uploadDocs.isPending}
                  onClick={() => fileInputRef.current?.click()}
                  className={cn(
                    "text-callout mt-3 flex w-full items-center justify-center gap-2 rounded-xl border border-hairline py-2.5 font-semibold text-label-primary",
                    "transition-all active:scale-[0.98]",
                    uploadDocs.isPending && "cursor-not-allowed opacity-60",
                  )}
                >
                  {uploadDocs.isPending ? (
                    <><Loader2 className="h-4 w-4 animate-spin" /> Uploading…</>
                  ) : (
                    <><Upload className="h-4 w-4" /> Add documents</>
                  )}
                </button>
              </>
            ) : (
              <EditInputsForm
                site={site}
                pending={updateSite.isPending}
                onCancel={() => setEditing(false)}
                onSave={(patch) =>
                  updateSite.mutate(
                    { siteId, patch },
                    {
                      onSuccess: () => {
                        setEditing(false);
                        toast.success("Inputs updated", {
                          description: "Re-score to update the ranking.",
                        });
                      },
                      onError: (err) =>
                        toast.error("Update failed", {
                          description:
                            err instanceof Error ? err.message : "Please try again.",
                        }),
                    },
                  )
                }
              />
            )}
          </Card>
        )}

        {/* Actions */}
        <div className="space-y-3">
          {/* Background evaluation in progress — safe to leave the page. */}
          {isRunning && (
            <div
              className={cn(
                "text-body w-full rounded-2xl border border-info/30 bg-info/10 py-3.5 font-semibold text-info",
                "flex flex-col items-center justify-center gap-1",
              )}
            >
              <span className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                {site.status === "scoring" ? "Scoring…" : "Evaluating…"}
              </span>
              <span className="text-caption-1 font-normal text-label-tertiary">
                Running in the background — you can leave this page and come back.
              </span>
            </div>
          )}

          {site.status === "error" && (
            <p className="text-caption-1 text-center text-danger">
              The last evaluation failed. Tap Run Evaluation to try again.
            </p>
          )}

          {canRun && !isRunning && (
            <button
              type="button"
              disabled={runEvaluation.isPending}
              onClick={() =>
                runEvaluation.mutate(siteId, {
                  onSuccess: () =>
                    toast.success("Evaluation started", {
                      description:
                        "Running in the background — you can leave this page; results appear when it finishes.",
                    }),
                  onError: (err) =>
                    toast.error("Couldn’t start evaluation", {
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
                <><Loader2 className="h-4 w-4 animate-spin" /> Starting…</>
              ) : (
                <><Play className="h-4 w-4" /> {runLabel}</>
              )}
            </button>
          )}

          {/* ── Post-evaluation human-in-the-loop decision ─────────────────── */}
          {/* Terminal states first: advanced (project exists), or rejected. */}
          {isAdvanced && advanceStatus?.project_id ? (
            <button
              type="button"
              onClick={() => router.push(`/projects/${advanceStatus.project_id}`)}
              className={cn(
                "text-body w-full rounded-2xl border border-success/30 bg-success/15 py-3.5 font-semibold text-success",
                "flex items-center justify-center gap-2 transition-all active:scale-[0.98]",
              )}
            >
              <CheckCircle2 className="h-4 w-4" /> Accepted — View Project
              <ChevronRight className="h-4 w-4" />
            </button>
          ) : advancePending ? (
            <button
              type="button"
              onClick={() => router.push("/queue")}
              className={cn(
                "text-body w-full rounded-2xl border border-warning/30 bg-warning/10 py-3.5 font-semibold text-warning",
                "flex items-center justify-center gap-2 transition-all active:scale-[0.98]",
              )}
            >
              <Clock className="h-4 w-4" /> Accepted — Advance Pending Approval
              <ChevronRight className="h-4 w-4" />
            </button>
          ) : finalVerdict === "rejected" ? (
            <>
              <div
                className={cn(
                  "text-body w-full rounded-2xl border border-danger/30 bg-danger/10 py-3.5 font-semibold text-danger",
                  "flex items-center justify-center gap-2",
                )}
              >
                <XCircle className="h-4 w-4" /> Rejected — Will not proceed
              </div>
              <p className="text-caption-1 text-center text-label-tertiary">
                This site is archived. You can permanently delete its record.
              </p>
              {!confirmDelete ? (
                <button
                  type="button"
                  onClick={() => setConfirmDelete(true)}
                  className={cn(
                    "text-body w-full rounded-2xl border border-danger/40 py-3.5 font-semibold text-danger",
                    "flex items-center justify-center gap-2 transition-all active:scale-[0.98]",
                  )}
                >
                  <Trash2 className="h-4 w-4" /> Delete Site Record
                </button>
              ) : (
                <div className="space-y-2">
                  <p className="text-caption-1 text-center font-medium text-danger">
                    Permanently delete this site and its evaluation? This can’t be undone.
                  </p>
                  <div className="flex gap-3">
                    <button
                      type="button"
                      onClick={() => setConfirmDelete(false)}
                      disabled={deleteSite.isPending}
                      className="text-body flex-1 rounded-2xl border border-hairline py-3.5 font-semibold text-label-secondary transition-all active:scale-[0.98]"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      disabled={deleteSite.isPending}
                      onClick={() =>
                        deleteSite.mutate(siteId, {
                          onSuccess: () => {
                            toast.success("Site deleted", {
                              description: "The site record has been permanently removed.",
                            });
                            router.push("/sites/archive");
                          },
                          onError: (err) =>
                            toast.error("Delete failed", {
                              description:
                                err instanceof Error ? err.message : "Please try again.",
                            }),
                        })
                      }
                      className={cn(
                        "text-body flex-1 rounded-2xl bg-danger py-3.5 font-semibold text-white",
                        "flex items-center justify-center gap-2 transition-all active:scale-[0.98]",
                        deleteSite.isPending && "cursor-not-allowed opacity-60",
                      )}
                    >
                      {deleteSite.isPending ? (
                        <><Loader2 className="h-4 w-4 animate-spin" /> Deleting…</>
                      ) : (
                        <><Trash2 className="h-4 w-4" /> Delete</>
                      )}
                    </button>
                  </div>
                </div>
              )}
            </>
          ) : isEvaluated ? (
            <>
              <p className="text-caption-1 text-center text-label-tertiary">
                Evaluation complete. This decision is yours — accept to move the site
                to the next phase, or reject to stop here.
              </p>
              <div className="flex gap-3">
                <button
                  type="button"
                  disabled={decideSite.isPending}
                  onClick={() =>
                    decideSite.mutate(
                      { siteId, decision: "accept" },
                      {
                        onSuccess: () =>
                          toast.success("Site accepted", {
                            description: "Advance to project requested (needs approval).",
                          }),
                        onError: (err) =>
                          toast.error("Accept failed", {
                            description:
                              err instanceof Error ? err.message : "Please try again.",
                          }),
                      },
                    )
                  }
                  className={cn(
                    "text-body flex-1 rounded-2xl bg-accent py-3.5 font-semibold text-white",
                    "flex items-center justify-center gap-2 transition-all active:scale-[0.98]",
                    decideSite.isPending && "cursor-not-allowed opacity-60",
                  )}
                >
                  {decideSite.isPending && decideSite.variables?.decision === "accept" ? (
                    <><Loader2 className="h-4 w-4 animate-spin" /> Accepting…</>
                  ) : (
                    <><CheckCircle2 className="h-4 w-4" /> Accept</>
                  )}
                </button>
                <button
                  type="button"
                  disabled={decideSite.isPending}
                  onClick={() =>
                    decideSite.mutate(
                      { siteId, decision: "reject" },
                      {
                        onSuccess: () =>
                          toast.success("Site rejected", {
                            description: "This site will not proceed.",
                          }),
                        onError: (err) =>
                          toast.error("Reject failed", {
                            description:
                              err instanceof Error ? err.message : "Please try again.",
                          }),
                      },
                    )
                  }
                  className={cn(
                    "text-body flex-1 rounded-2xl border border-danger/40 py-3.5 font-semibold text-danger",
                    "flex items-center justify-center gap-2 transition-all active:scale-[0.98]",
                    decideSite.isPending && "cursor-not-allowed opacity-60",
                  )}
                >
                  {decideSite.isPending && decideSite.variables?.decision === "reject" ? (
                    <><Loader2 className="h-4 w-4 animate-spin" /> Rejecting…</>
                  ) : (
                    <><XCircle className="h-4 w-4" /> Reject</>
                  )}
                </button>
              </div>
            </>
          ) : null}

          {decideSite.isError && (
            <p className="text-caption-1 text-center text-danger">
              {decideSite.error?.message ?? "Decision failed."}
            </p>
          )}
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

// ── Edit Inputs Form ────────────────────────────────────────────────────────

const WORKLOAD_OPTIONS: { value: string; label: string }[] = [
  { value: "ai_hpc", label: "AI / HPC" },
  { value: "hyperscale", label: "Hyperscale" },
  { value: "enterprise_colo", label: "Enterprise Colo" },
  { value: "edge", label: "Edge" },
  { value: "unknown", label: "Unknown" },
];

type EditPatch = {
  county?: string;
  acres?: number;
  asking_price?: number;
  target_workload?: string;
  target_mw?: number;
};

function EditInputsForm({
  site,
  pending,
  onSave,
  onCancel,
}: {
  site: Site;
  pending: boolean;
  onSave: (patch: EditPatch) => void;
  onCancel: () => void;
}) {
  const prop = (site.property ?? {}) as {
    county?: string | null;
    acres?: number | null;
    asking_price?: number | null;
  };
  const [county, setCounty] = React.useState(prop.county ?? "");
  const [acres, setAcres] = React.useState(prop.acres != null ? String(prop.acres) : "");
  const [askingPrice, setAskingPrice] = React.useState(
    prop.asking_price != null ? String(prop.asking_price) : "",
  );
  const [workload, setWorkload] = React.useState(site.target_workload ?? "unknown");
  const [mw, setMw] = React.useState(site.target_mw != null ? String(site.target_mw) : "");

  const numOrUndef = (s: string): number | undefined => {
    const t = s.trim();
    if (t === "") return undefined;
    const n = Number(t);
    return Number.isFinite(n) ? n : undefined;
  };

  const inputCls =
    "w-full rounded-xl border border-hairline bg-bg-elevated px-3 py-2 text-callout text-label-primary outline-none focus:border-accent";
  const labelCls = "text-caption-1 mb-1 block font-medium text-label-secondary";

  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Target workload</label>
        <select
          className={inputCls}
          value={workload}
          onChange={(e) => setWorkload(e.target.value)}
        >
          {WORKLOAD_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelCls}>Target MW</label>
          <input
            className={inputCls}
            inputMode="decimal"
            value={mw}
            onChange={(e) => setMw(e.target.value)}
            placeholder="e.g. 100"
          />
        </div>
        <div>
          <label className={labelCls}>Acres</label>
          <input
            className={inputCls}
            inputMode="decimal"
            value={acres}
            onChange={(e) => setAcres(e.target.value)}
            placeholder="e.g. 250"
          />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelCls}>Asking price (USD)</label>
          <input
            className={inputCls}
            inputMode="decimal"
            value={askingPrice}
            onChange={(e) => setAskingPrice(e.target.value)}
            placeholder="e.g. 5000000"
          />
        </div>
        <div>
          <label className={labelCls}>County</label>
          <input
            className={inputCls}
            value={county}
            onChange={(e) => setCounty(e.target.value)}
            placeholder="County"
          />
        </div>
      </div>
      <div className="flex gap-3 pt-1">
        <button
          type="button"
          onClick={onCancel}
          disabled={pending}
          className="text-callout flex-1 rounded-xl border border-hairline py-2.5 font-semibold text-label-secondary transition-all active:scale-[0.98]"
        >
          Cancel
        </button>
        <button
          type="button"
          disabled={pending}
          onClick={() =>
            onSave({
              county: county.trim() || undefined,
              acres: numOrUndef(acres),
              asking_price: numOrUndef(askingPrice),
              target_workload: workload || undefined,
              target_mw: numOrUndef(mw),
            })
          }
          className={cn(
            "text-callout flex-1 rounded-xl bg-accent py-2.5 font-semibold text-white",
            "flex items-center justify-center gap-2 transition-all active:scale-[0.98]",
            pending && "cursor-not-allowed opacity-60",
          )}
        >
          {pending ? (
            <><Loader2 className="h-4 w-4 animate-spin" /> Saving…</>
          ) : (
            "Save inputs"
          )}
        </button>
      </div>
    </div>
  );
}
