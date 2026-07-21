"use client";

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  ChevronLeft,
  Download,
  FileText,
  Loader2,
} from "lucide-react";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { useSiteReport, siteReportPdfUrl } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * /sites/[id]/report — DataSite Site Evaluation Report (in-app view).
 *
 * Renders the structured report from GET /v1/sites/{id}/report and offers a
 * "Download PDF" button (GET /v1/sites/{id}/report.pdf). This is the human-
 * facing report the journey "Datasite report" deliverable links to.
 */
export default function SiteReportPage() {
  const params = useParams();
  const router = useRouter();
  const siteId = String(params?.id ?? "");
  const { data, isLoading, error } = useSiteReport(siteId);

  const backBtn = (
    <button
      type="button"
      onClick={() => router.push(`/sites/${encodeURIComponent(siteId)}`)}
      aria-label="Back to site"
      className="no-tap-highlight flex h-9 w-9 items-center justify-center rounded-full text-accent active:opacity-70"
    >
      <ChevronLeft className="h-6 w-6" />
    </button>
  );

  if (isLoading) {
    return (
      <MobileShell>
        <TopBar title="DataSite Report" left={backBtn} />
        <div className="flex items-center justify-center py-20 text-label-tertiary">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      </MobileShell>
    );
  }

  if (error || !data?.report) {
    return (
      <MobileShell>
        <TopBar title="DataSite Report" left={backBtn} />
        <div className="mx-auto w-full max-w-[708px] px-4 py-16 text-center md:max-w-4xl">
          <p className="text-body text-label-primary">Couldn’t load the report.</p>
          <p className="mt-1 text-footnote text-label-secondary">
            The site may not have been evaluated yet.
          </p>
          <button
            type="button"
            onClick={() => router.push(`/sites/${encodeURIComponent(siteId)}`)}
            className="mt-4 inline-flex items-center gap-1.5 text-callout font-semibold text-accent"
          >
            <ArrowLeft className="h-4 w-4" /> Back to site
          </button>
        </div>
      </MobileShell>
    );
  }

  const r = data.report;
  const total = r.score.total_weighted;
  const band = r.score.band;
  const bandColor =
    band === "strong"
      ? "text-success"
      : band === "poor"
        ? "text-danger"
        : "text-warning";

  return (
    <MobileShell>
      <TopBar title="DataSite Report" left={backBtn} />
      <div className="mx-auto w-full max-w-[708px] px-4 pt-3 pb-16 md:max-w-4xl md:px-8">
        {/* Header + download */}
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-caption-1 font-semibold uppercase tracking-wide text-accent">
              Site Evaluation Report
            </p>
            <h1 className="mt-0.5 text-title-1 font-bold text-label-primary">
              {r.location}
            </h1>
            <p className="mt-0.5 text-footnote text-label-secondary">
              {[r.target_workload, r.target_mw ? `${r.target_mw} MW` : null,
                r.property?.acres ? `${r.property.acres} acres` : null]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </div>
          <a
            href={siteReportPdfUrl(siteId)}
            target="_blank"
            rel="noopener noreferrer"
            className="no-tap-highlight ease-ios flex shrink-0 items-center gap-1.5 rounded-full bg-accent px-3.5 py-2 text-caption-1 font-semibold text-white active:scale-[0.97] duration-tap"
          >
            <Download className="h-4 w-4" /> PDF
          </a>
        </div>

        {/* Score + verdict banner */}
        <div className="mb-5 flex items-center gap-4 rounded-2xl bg-bg-elevated px-4 py-4 shadow-card">
          <div className="text-center">
            <p className={cn("text-large-title font-bold tabular-nums", bandColor)}>
              {total != null ? total.toFixed(0) : "—"}
            </p>
            <p className="text-caption-2 text-label-tertiary">/ 100</p>
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-caption-1 text-label-tertiary">Verdict</p>
            <p className="text-headline font-semibold text-label-primary">
              {r.verdict.label}
            </p>
            {r.kill_switches_triggered.length > 0 && (
              <p className="mt-1 text-caption-1 font-semibold text-danger">
                Kill-switches: {r.kill_switches_triggered.join(", ")}
              </p>
            )}
          </div>
        </div>

        {/* Recommendation */}
        {r.recommendation.summary && (
          <Section title="Recommendation">
            <p className="text-callout leading-relaxed text-label-secondary">
              {r.recommendation.summary}
            </p>
          </Section>
        )}
        <BulletSection title="Strengths" items={r.recommendation.strengths} />
        <BulletSection title="Risks" items={r.recommendation.risks} tone="danger" />
        <BulletSection title="Conditions" items={r.recommendation.conditions} />
        <BulletSection title="Next steps" items={r.recommendation.next_steps} />

        {/* Scorecard */}
        <Section title="Scorecard">
          <div className="overflow-hidden rounded-xl border border-hairline">
            <div className="grid grid-cols-[1fr_auto_auto_auto] gap-x-3 bg-bg-tertiary px-3 py-2 text-caption-2 font-semibold uppercase tracking-wide text-label-tertiary">
              <span>Criterion</span>
              <span className="text-right">Score</span>
              <span className="text-right">Weight</span>
              <span className="text-right">Wtd</span>
            </div>
            {r.criteria.map((c) => (
              <div
                key={c.key}
                className="grid grid-cols-[1fr_auto_auto_auto] gap-x-3 border-t border-hairline px-3 py-2 text-footnote"
              >
                <span className="truncate text-label-primary">
                  {c.label}
                  {c.kill_switch_triggered && (
                    <span className="ml-1 text-danger">(kill)</span>
                  )}
                </span>
                <span className="text-right tabular-nums text-label-primary">
                  {c.score != null ? c.score.toFixed(0) : "—"}
                </span>
                <span className="text-right tabular-nums text-label-tertiary">
                  {c.weight != null ? `${(c.weight * 100).toFixed(0)}%` : "—"}
                </span>
                <span className="text-right tabular-nums text-label-tertiary">
                  {c.weighted_score != null ? c.weighted_score.toFixed(2) : "—"}
                </span>
              </div>
            ))}
          </div>
        </Section>

        {/* Evidence */}
        {r.criteria.some((c) => c.evidence) && (
          <Section title="Evidence by criterion">
            <div className="space-y-3">
              {r.criteria
                .filter((c) => c.evidence)
                .map((c) => (
                  <div key={c.key}>
                    <p className="text-footnote font-semibold text-label-primary">
                      {c.label}
                    </p>
                    <p className="text-footnote text-label-secondary">{c.evidence}</p>
                  </div>
                ))}
            </div>
          </Section>
        )}

        {/* Documents analyzed */}
        {r.documents.length > 0 && (
          <Section title="Documents analyzed">
            <div className="space-y-1.5">
              {r.documents.map((d, i) => (
                <div key={i} className="flex items-center gap-2 text-footnote">
                  <FileText className="h-4 w-4 shrink-0 text-label-tertiary" />
                  <span className="truncate text-label-primary">
                    {d.filename ?? d.doc_id}
                  </span>
                  {d.type && (
                    <span className="ml-auto shrink-0 text-caption-1 text-label-tertiary">
                      {d.type}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </Section>
        )}

        <p className="mt-6 text-caption-2 text-label-quaternary">
          Generated {new Date(r.generated_at).toLocaleString("en-US")}
        </p>
      </div>
    </MobileShell>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-5">
      <p className="mb-1.5 text-caption-1 font-semibold uppercase tracking-wide text-label-tertiary">
        {title}
      </p>
      {children}
    </section>
  );
}

function BulletSection({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone?: "danger";
}) {
  if (!items || items.length === 0) return null;
  return (
    <Section title={title}>
      <ul className="space-y-1">
        {items.map((it, i) => (
          <li key={i} className="flex gap-2 text-callout text-label-secondary">
            <span
              className={cn(
                "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full",
                tone === "danger" ? "bg-danger" : "bg-accent",
              )}
            />
            <span>{it}</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}
