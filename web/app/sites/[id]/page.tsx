"use client";

/**
 * /sites/[id] — Site Detail page (Sprint DC.2)
 *
 * Shows: address, status badge, total score, verdict, 10-criteria scorecard,
 * recommendation text, documents, Run Evaluation button, Advance to Project button.
 *
 * Design: dark Quill theme, iOS-style cards.
 */

import * as React from "react";
import { useRouter, useParams } from "next/navigation";
import {
  ArrowLeft,
  Building2,
  ChevronRight,
  FileText,
  FolderKanban,
  Loader2,
  Play,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { useSite, useRunSiteEvaluation, useCreateProject } from "@/lib/api";
import type { Site } from "@/lib/schemas";

// ── Scoring criteria config ───────────────────────────────────────────────────

const CRITERIA = [
  { key: "power", label: "Power", weight: 0.30 },
  { key: "fiber", label: "Fiber & Connectivity", weight: 0.15 },
  { key: "permitting", label: "Permitting", weight: 0.15 },
  { key: "environmental", label: "Environmental", weight: 0.15 },
  { key: "land", label: "Land", weight: 0.10 },
  { key: "water", label: "Water", weight: 0.05 },
  { key: "market", label: "Market", weight: 0.05 },
  { key: "financial", label: "Financial", weight: 0.03 },
  { key: "title", label: "Title", weight: 0.01 },
  { key: "geotechnical", label: "Geotechnical", weight: 0.01 },
] as const;

// ── Helpers ───────────────────────────────────────────────────────────────────

function statusBadge(status: string): { label: string; cls: string } {
  switch (status) {
    case "intake": return { label: "Intake", cls: "text-label-secondary bg-bg-elevated" };
    case "researching": return { label: "Researching", cls: "text-blue-400 bg-blue-400/10" };
    case "scoring": return { label: "Scoring", cls: "text-purple-400 bg-purple-400/10" };
    case "review": return { label: "Review", cls: "text-yellow-400 bg-yellow-400/10" };
    case "decided": return { label: "Decided", cls: "text-green-400 bg-green-400/10" };
    default: return { label: status, cls: "text-label-secondary bg-bg-elevated" };
  }
}

function verdictInfo(verdict: string | null | undefined): { label: string; cls: string } {
  switch (verdict) {
    case "strong_recommend": return { label: "Strong Recommend", cls: "text-green-400 bg-green-400/10" };
    case "conditional": return { label: "Conditional", cls: "text-blue-400 bg-blue-400/10" };
    case "weak": return { label: "Weak", cls: "text-yellow-400 bg-yellow-400/10" };
    case "no_go": return { label: "No-Go", cls: "text-red-400 bg-red-400/10" };
    default: return { label: verdict ?? "—", cls: "text-label-tertiary bg-bg-elevated" };
  }
}

function siteAddress(site: Site): string {
  const p = site.property ?? {};
  const parts = [p.address, p.city, p.state, p.zip].filter(Boolean);
  return parts.join(", ") || "Unknown Address";
}

function scoreBarColor(score: number): string {
  if (score >= 70) return "bg-green-500";
  if (score >= 50) return "bg-yellow-500";
  return "bg-red-500";
}

function totalScoreColor(score: number | null | undefined): string {
  if (score == null) return "text-label-tertiary";
  if (score >= 70) return "text-green-400";
  if (score >= 50) return "text-yellow-400";
  return "text-red-400";
}

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-2xl bg-chrome/80 border border-separator/40 p-5 mb-4", className)}>
      {children}
    </div>
  );
}

// ── Scorecard ─────────────────────────────────────────────────────────────────

function Scorecard({ site }: { site: Site }) {
  const criteria = site.scores?.criteria ?? {};

  return (
    <Card>
      <p className="text-callout font-semibold text-label-primary mb-4">Scorecard</p>
      <div className="overflow-x-auto -mx-5">
        <table className="w-full text-caption-1 min-w-[400px]">
          <thead>
            <tr className="border-b border-separator/30">
              <th className="text-left pl-5 pr-2 py-2 font-semibold text-label-secondary">Criterion</th>
              <th className="text-right px-2 py-2 font-semibold text-label-secondary">Score</th>
              <th className="text-right px-2 py-2 font-semibold text-label-secondary">Weight</th>
              <th className="text-right pr-5 pl-2 py-2 font-semibold text-label-secondary">Weighted</th>
            </tr>
          </thead>
          <tbody>
            {CRITERIA.map((c) => {
              const entry = criteria[c.key] ?? {};
              const score = entry.score ?? null;
              const weight = entry.weight ?? c.weight;
              const weighted = entry.weighted_score ?? (score != null ? score * weight : null);
              return (
                <tr key={c.key} className="border-b border-separator/20 last:border-0">
                  <td className="pl-5 pr-2 py-2.5">
                    <span className="text-label-primary">{c.label}</span>
                  </td>
                  <td className="px-2 py-2.5 text-right">
                    {score != null ? (
                      <span className="tabular-nums text-label-primary">{score.toFixed(1)}</span>
                    ) : (
                      <span className="text-label-quaternary">—</span>
                    )}
                  </td>
                  <td className="px-2 py-2.5 text-right text-label-secondary tabular-nums">
                    {(weight * 100).toFixed(0)}%
                  </td>
                  <td className="pr-5 pl-2 py-2.5 text-right">
                    {weighted != null ? (
                      <span className="tabular-nums font-medium text-label-primary">
                        {weighted.toFixed(2)}
                      </span>
                    ) : (
                      <span className="text-label-quaternary">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SiteDetailPage() {
  const router = useRouter();
  const params = useParams();
  const siteId = params.id as string;

  const { data: site, isLoading, error } = useSite(siteId);
  const runEvaluation = useRunSiteEvaluation({
    onSuccess: () => {},
  });
  const createProject = useCreateProject({
    onSuccess: (project) => {
      router.push(`/projects/${project.id}`);
    },
  });

  if (isLoading) {
    return (
      <MobileShell>
        <TopBar
          title="Site"
          left={
            <button type="button" onClick={() => router.back()} className="text-accent font-semibold text-callout flex items-center gap-1">
              <ArrowLeft className="h-4 w-4" /> Sites
            </button>
          }
        />
        <div className="flex items-center justify-center pt-24">
          <Loader2 className="h-8 w-8 text-label-quaternary animate-spin" />
        </div>
      </MobileShell>
    );
  }

  if (error || !site) {
    return (
      <MobileShell>
        <TopBar
          title="Site"
          left={
            <button type="button" onClick={() => router.back()} className="text-accent font-semibold text-callout flex items-center gap-1">
              <ArrowLeft className="h-4 w-4" /> Sites
            </button>
          }
        />
        <div className="px-4 pt-6 text-center text-label-secondary">
          {error ? "Failed to load site." : "Site not found."}
        </div>
      </MobileShell>
    );
  }

  const totalScore = site.scores?.total_weighted;
  const verdict = site.recommendation?.verdict;
  const { label: statusLabel, cls: statusCls } = statusBadge(site.status);
  const { label: verdictLabel, cls: verdictCls } = verdictInfo(verdict);
  const canAdvance = verdict === "strong_recommend" || verdict === "conditional";
  const canRun = site.status === "intake";
  const address = siteAddress(site);
  const docs = site.documents ?? [];

  function handleAdvanceToProject() {
    const name = `${address} — ${workloadLabel(site.target_workload ?? null)}`;
    createProject.mutate({
      name,
      address,
      site_id: site.site_id,
      site_score: totalScore ?? undefined,
      site_verdict: verdict ?? undefined,
      workload_type: site.target_workload ?? undefined,
      phase: "site_control",
      status: "active",
    });
  }

  return (
    <MobileShell>
      <TopBar
        title={address.split(",")[0]}
        left={
          <button
            type="button"
            onClick={() => router.back()}
            className="text-accent font-semibold text-callout flex items-center gap-1"
          >
            <ArrowLeft className="h-4 w-4" />
            Sites
          </button>
        }
      />

      <div className="px-4 pt-3 pb-12">
        {/* Hero — score + verdict + status */}
        <Card>
          <div className="flex items-start justify-between mb-3">
            <div>
              <p className="text-callout font-medium text-label-secondary mb-1">{address}</p>
              <div className="flex flex-wrap gap-2">
                <span className={cn("text-caption-1 font-semibold rounded-full px-2 py-0.5", statusCls)}>
                  {statusLabel}
                </span>
                {site.target_workload && (
                  <span className="text-caption-1 font-medium text-label-secondary bg-bg-elevated rounded-full px-2 py-0.5">
                    {workloadLabel(site.target_workload)}
                  </span>
                )}
                {site.target_mw != null && (
                  <span className="flex items-center gap-0.5 text-caption-1 text-label-secondary">
                    <Zap className="h-3 w-3 text-yellow-400" />
                    {site.target_mw} MW
                  </span>
                )}
              </div>
            </div>
            {totalScore != null && (
              <div className="text-right ml-4">
                <p className={cn("text-large-title font-bold tabular-nums", totalScoreColor(totalScore))}>
                  {totalScore.toFixed(0)}
                </p>
                <p className="text-caption-1 text-label-tertiary">/100</p>
              </div>
            )}
          </div>

          {/* Score bar */}
          {totalScore != null && (
            <div className="h-2 bg-bg-elevated rounded-full overflow-hidden mb-3">
              <div
                className={cn("h-full rounded-full transition-all", scoreBarColor(totalScore))}
                style={{ width: `${Math.min(100, totalScore)}%` }}
              />
            </div>
          )}

          {/* Verdict */}
          {verdict && (
            <div className="flex items-center justify-between">
              <span className="text-footnote text-label-secondary">Verdict</span>
              <span className={cn("text-callout font-semibold rounded-full px-3 py-1", verdictCls)}>
                {verdictLabel}
              </span>
            </div>
          )}
        </Card>

        {/* Recommendation */}
        {site.recommendation?.summary && (
          <Card>
            <p className="text-callout font-semibold text-label-primary mb-2">Recommendation</p>
            <p className="text-callout text-label-secondary leading-relaxed">
              {site.recommendation.summary}
            </p>

            {(site.recommendation.strengths?.length ?? 0) > 0 && (
              <div className="mt-3">
                <p className="text-footnote font-semibold text-green-400 mb-1.5">Strengths</p>
                <ul className="space-y-1">
                  {site.recommendation.strengths!.map((s, i) => (
                    <li key={i} className="text-caption-1 text-label-secondary flex gap-2">
                      <span className="text-green-400 mt-0.5">✓</span>
                      <span>{s}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {(site.recommendation.risks?.length ?? 0) > 0 && (
              <div className="mt-3">
                <p className="text-footnote font-semibold text-yellow-400 mb-1.5">Risks</p>
                <ul className="space-y-1">
                  {site.recommendation.risks!.map((r, i) => (
                    <li key={i} className="text-caption-1 text-label-secondary flex gap-2">
                      <span className="text-yellow-400 mt-0.5">⚠</span>
                      <span>{r}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Card>
        )}

        {/* Scorecard */}
        <Scorecard site={site} />

        {/* Documents */}
        {docs.length > 0 && (
          <Card>
            <p className="text-callout font-semibold text-label-primary mb-3">Documents</p>
            <div className="space-y-2">
              {docs.map((doc) => (
                <div
                  key={doc.doc_id}
                  className="flex items-center gap-3 p-3 rounded-xl bg-bg-elevated"
                >
                  <FileText className="h-4 w-4 text-label-tertiary shrink-0" />
                  <span className="text-callout text-label-primary truncate">
                    {doc.filename ?? doc.doc_id}
                  </span>
                  {doc.type && (
                    <span className="ml-auto text-caption-1 text-label-tertiary shrink-0">{doc.type}</span>
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
              onClick={() => runEvaluation.mutate(siteId)}
              className={cn(
                "w-full py-3.5 rounded-2xl font-semibold text-body",
                "border border-accent text-accent",
                "flex items-center justify-center gap-2",
                "transition-all active:scale-[0.98]",
                runEvaluation.isPending && "opacity-60 cursor-not-allowed",
              )}
            >
              {runEvaluation.isPending ? (
                <><Loader2 className="h-4 w-4 animate-spin" /> Running…</>
              ) : (
                <><Play className="h-4 w-4" /> Run Evaluation</>
              )}
            </button>
          )}

          {canAdvance && (
            <button
              type="button"
              disabled={createProject.isPending}
              onClick={handleAdvanceToProject}
              className={cn(
                "w-full py-3.5 rounded-2xl font-semibold text-body",
                "bg-accent text-white",
                "flex items-center justify-center gap-2",
                "transition-all active:scale-[0.98]",
                createProject.isPending && "opacity-60 cursor-not-allowed",
              )}
            >
              {createProject.isPending ? (
                <><Loader2 className="h-4 w-4 animate-spin" /> Creating Project…</>
              ) : (
                <><FolderKanban className="h-4 w-4" /> Advance to Project</>
              )}
            </button>
          )}
        </div>
      </div>
    </MobileShell>
  );
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
