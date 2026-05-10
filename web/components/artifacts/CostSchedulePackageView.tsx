"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import type { CostSchedulePackage } from "@/lib/schemas";
import { ArtifactCard, ArtifactCardBody, ArtifactCardHeader } from "./shared/ArtifactCard";
import { Section } from "./shared/Section";
import { DataTable, SubtotalRow, type DataTableColumn } from "./shared/DataTable";
import { CitationList } from "./shared/Citation";
import { ConfidenceBadge } from "./shared/Confidence";
import { MarkdownBlock } from "./shared/MarkdownBlock";
import { StatPill } from "./shared/StatPill";

function formatUSD(n: number | null | undefined, compact = false): string {
  if (n == null) return "—";
  if (compact) {
    if (Math.abs(n) >= 1_000_000_000)
      return `$${(n / 1_000_000_000).toFixed(2)}B`;
    if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
    if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);
}

type Tab = "cost" | "schedule" | "basis";

export function CostSchedulePackageView({
  artifact,
  mode = "view",
}: {
  artifact: CostSchedulePackage;
  mode?: "view" | "print";
}) {
  const meta = artifact.metadata;
  const est = meta.estimate;
  const sched = meta.schedule;
  const [activeTab, setActiveTab] = React.useState<Tab>("cost");
  const isPrint = mode === "print";

  const citations = Array.isArray(artifact.citations)
    ? (artifact.citations as Array<{ kind?: string; ref?: string; note?: string; url?: string }>)
    : [];

  // Compute CSI division grouping
  const groupedRows = React.useMemo(() => {
    if (!est?.rows) return [];
    const groups = new Map<string, typeof est.rows>();
    for (const row of est.rows) {
      const div = row.csi_section?.split(" ")?.[0] ?? "00";
      if (!groups.has(div)) groups.set(div, []);
      groups.get(div)!.push(row);
    }
    return Array.from(groups.entries()).map(([div, rows]) => ({
      div,
      rows,
      subtotal: rows.reduce((sum, r) => sum + (r.extended_usd ?? 0), 0),
    }));
  }, [est?.rows]);

  const tabs: { key: Tab; label: string }[] = [
    { key: "cost", label: "Cost" },
    { key: "schedule", label: "Schedule" },
    { key: "basis", label: "Basis of Estimate" },
  ];

  const totalDays = sched?.total_duration_days ?? meta.headline_metrics?.total_duration_days;

  return (
    <div className="space-y-4">
      {/* ── Hero ── */}
      <ArtifactCard>
        <ArtifactCardHeader>
          <div className="flex items-center gap-2 flex-wrap mb-2">
            <span className="inline-flex items-center rounded-lg bg-accent px-3 py-1.5 text-headline font-bold text-white">
              Class {meta.aace_class}
            </span>
            <span className="text-footnote text-label-tertiary">
              Level {meta.schedule_level} schedule · {meta.currency ?? "USD"}{" "}
              {meta.base_year}
            </span>
            <ConfidenceBadge confidence={artifact.confidence ?? 0} />
          </div>
        </ArtifactCardHeader>
        <ArtifactCardBody>
          <p className="text-callout text-label-primary leading-relaxed mb-4">
            {artifact.summary}
          </p>
          <div className="grid grid-cols-2 gap-3">
            <StatPill
              value={formatUSD(est?.total_usd, true)}
              label="Total estimate"
              subValue={est?.total_per_mw_usd ? `${formatUSD(est.total_per_mw_usd, true)}/MW` : undefined}
              accent
            />
            <StatPill
              value={totalDays ? `${totalDays}d` : "—"}
              label="Schedule duration"
              subValue={
                sched?.milestones?.[0]?.target_date && sched?.milestones?.[sched.milestones.length - 1]?.target_date
                  ? `${sched.milestones[0].target_date} → ${sched.milestones[sched.milestones.length - 1].target_date}`
                  : undefined
              }
            />
            {est?.contingency && (
              <StatPill
                value={formatUSD(est.contingency.amount_usd, true)}
                label={`Contingency (${Math.round(est.contingency.pct_of_direct_plus_indirect ?? 0)}%)`}
              />
            )}
            {est?.escalation && (
              <StatPill
                value={formatUSD(est.escalation.amount_usd, true)}
                label={`Escalation (${est.escalation.annual_pct}%/yr → ${est.escalation.midpoint_year})`}
              />
            )}
          </div>
        </ArtifactCardBody>
      </ArtifactCard>

      {/* ── Tabs or stacked sections in print ── */}
      {!isPrint ? (
        <>
          {/* Tab bar */}
          <div className="flex rounded-xl bg-bg-elevated p-1 gap-1">
            {tabs.map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => setActiveTab(t.key)}
                className={cn(
                  "flex-1 min-h-[44px] rounded-lg text-callout font-medium transition-colors no-tap-highlight",
                  activeTab === t.key
                    ? "bg-bg text-label-primary shadow-sm"
                    : "text-label-secondary active:bg-bg-tertiary/60",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>

          {activeTab === "cost" && <CostTab est={est} groupedRows={groupedRows} />}
          {activeTab === "schedule" && <ScheduleTab sched={sched} />}
          {activeTab === "basis" && <BasisTab meta={meta} artifact={artifact} />}
        </>
      ) : (
        // Print: stack all sections
        <>
          <CostTab est={est} groupedRows={groupedRows} printForceOpen />
          <ScheduleTab sched={sched} printForceOpen />
          <BasisTab meta={meta} artifact={artifact} printForceOpen />
        </>
      )}

      {/* ── Risk register ── */}
      {meta.risk_register?.length > 0 && (
        <Section
          title={`Risk register (${meta.risk_register.length})`}
          defaultOpen={false}
          printForceOpen={isPrint}
        >
          <div className="space-y-2 pt-1">
            {meta.risk_register.map((r, i) => (
              <div
                key={r.id ?? i}
                className="rounded-lg bg-bg-tertiary px-3 py-2.5"
              >
                <div className="flex items-start gap-2">
                  <span
                    className={cn(
                      "mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-caption-2 font-medium",
                      r.likelihood === "high"
                        ? "bg-danger/15 text-danger"
                        : r.likelihood === "medium"
                          ? "bg-warning/15 text-warning"
                          : "bg-success/15 text-success",
                    )}
                  >
                    {r.likelihood}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-callout text-label-primary">
                      {r.description}
                    </div>
                    {r.mitigation && (
                      <div className="mt-1 text-footnote text-label-secondary">
                        Mitigation: {r.mitigation}
                      </div>
                    )}
                    <div className="mt-1 flex gap-3 text-caption-1 text-label-tertiary flex-wrap">
                      <span>{r.category}</span>
                      {r.impact_usd_low != null && r.impact_usd_high != null && (
                        <span>
                          Cost impact: {formatUSD(r.impact_usd_low, true)} –{" "}
                          {formatUSD(r.impact_usd_high, true)}
                        </span>
                      )}
                      {r.schedule_impact_days_low != null && (
                        <span>
                          Schedule: {r.schedule_impact_days_low}–
                          {r.schedule_impact_days_high}d
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* ── Missing info to next class ── */}
      {meta.missing_info_to_next_class?.length > 0 && (
        <Section
          title="To unlock the next class"
          defaultOpen={false}
          printForceOpen={isPrint}
        >
          <ul className="space-y-2 pt-1">
            {meta.missing_info_to_next_class.map((m, i) => (
              <li key={i} className="rounded-lg bg-bg-tertiary px-3 py-2.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="text-callout font-medium text-label-primary">
                    {m.deliverable}
                  </div>
                  <span className="shrink-0 rounded-full bg-accent/15 px-2 py-0.5 text-caption-1 text-accent">
                    → Class {m.would_unlock_class}
                  </span>
                </div>
                {m.rationale && (
                  <div className="mt-1 text-footnote text-label-secondary">
                    {m.rationale}
                  </div>
                )}
                {m.estimated_cost_to_complete_usd != null && (
                  <div className="mt-0.5 text-caption-1 text-label-tertiary">
                    Est. cost: {formatUSD(m.estimated_cost_to_complete_usd, true)}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* ── Citations ── */}
      <CitationList citations={citations} />

      {/* ── Library version / caveats ── */}
      {(meta.library_version || artifact.escalation_reasons?.length) && (
        <div className="rounded-lg bg-bg-elevated px-4 py-3 text-footnote text-label-tertiary space-y-1">
          {meta.library_version && (
            <div>Cost library: {meta.library_version}</div>
          )}
          {artifact.escalation_reasons?.length ? (
            <div>
              Flags: {artifact.escalation_reasons.join(", ")}
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

/* ── Cost Tab ─────────────────────────────────────────────────────────── */

const COST_COLUMNS: DataTableColumn<Record<string, unknown>>[] = [
  {
    key: "csi_section",
    label: "CSI",
    className: "w-20 font-mono text-label-tertiary",
  },
  { key: "description", label: "Description", className: "min-w-[140px]" },
  {
    key: "quantity",
    label: "Qty",
    className: "text-right tabular-nums",
    render: (r) => (
      <span className="tabular-nums">
        {r.quantity != null ? Number(r.quantity).toLocaleString() : "—"}
      </span>
    ),
  },
  { key: "unit", label: "Unit", className: "w-12" },
  {
    key: "unit_rate_usd",
    label: "Rate",
    className: "text-right tabular-nums",
    render: (r) => formatUSD(r.unit_rate_usd as number),
  },
  {
    key: "extended_usd",
    label: "Total",
    className: "text-right tabular-nums font-medium",
    render: (r) => formatUSD(r.extended_usd as number),
  },
  {
    key: "confidence",
    label: "Conf.",
    className: "text-right tabular-nums",
    render: (r) =>
      r.confidence != null
        ? `${Math.round((r.confidence as number) * 100)}%`
        : "—",
  },
];

function CostTab({
  est,
  groupedRows,
  printForceOpen,
}: {
  est: CostSchedulePackage["metadata"]["estimate"];
  groupedRows: Array<{ div: string; rows: typeof est.rows; subtotal: number }>;
  printForceOpen?: boolean;
}) {
  if (!est) {
    return (
      <div className="text-callout text-label-secondary py-4 text-center">
        No cost data available.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Summary stats */}
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-xl bg-bg-elevated px-4 py-3">
          <div className="text-callout text-label-tertiary text-caption-1 uppercase tracking-wider mb-1">
            Base direct
          </div>
          <div className="text-title-3 font-bold text-label-primary tabular-nums">
            {formatUSD(est.subtotal_direct_usd, true)}
          </div>
        </div>
        <div className="rounded-xl bg-bg-elevated px-4 py-3">
          <div className="text-callout text-label-tertiary text-caption-1 uppercase tracking-wider mb-1">
            Grand total
          </div>
          <div className="text-title-3 font-bold text-accent tabular-nums">
            {formatUSD(est.total_usd, true)}
          </div>
        </div>
      </div>

      {/* Line items by CSI division */}
      {groupedRows.map(({ div, rows, subtotal }) => (
        <Section
          key={div}
          title={`Division ${div}`}
          defaultOpen={groupedRows.length <= 5}
          printForceOpen={printForceOpen}
        >
          <DataTable
            columns={COST_COLUMNS}
            rows={rows as Record<string, unknown>[]}
            keyField="csi_section"
          />
          <SubtotalRow
            label={`Division ${div} subtotal`}
            value={formatUSD(subtotal)}
          />
        </Section>
      ))}

      {/* Indirects */}
      {est.indirects?.length > 0 && (
        <Section
          title="Indirect costs"
          defaultOpen={false}
          printForceOpen={printForceOpen}
        >
          <div className="space-y-1 pt-1">
            {est.indirects.map((ind, i) => (
              <div
                key={i}
                className="flex justify-between text-callout py-1.5 border-b border-separator/20"
              >
                <span className="text-label-secondary">
                  {ind.label}
                  {ind.pct_of_direct != null && (
                    <span className="text-label-tertiary ml-1">
                      ({ind.pct_of_direct}%)
                    </span>
                  )}
                </span>
                <span className="tabular-nums text-label-primary">
                  {formatUSD(ind.amount_usd)}
                </span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Roll-up */}
      <div className="rounded-xl bg-bg-elevated px-4 py-3 space-y-1">
        <SubtotalRow
          label="Direct subtotal"
          value={formatUSD(est.subtotal_direct_usd)}
        />
        {est.indirects?.map((ind, i) => (
          <SubtotalRow
            key={i}
            label={ind.label}
            value={formatUSD(ind.amount_usd)}
          />
        ))}
        {est.contingency && (
          <SubtotalRow
            label={`Contingency (${Math.round(est.contingency.pct_of_direct_plus_indirect)}%)`}
            value={formatUSD(est.contingency.amount_usd)}
          />
        )}
        {est.escalation && (
          <SubtotalRow
            label={`Escalation (${est.escalation.annual_pct}%/yr → ${est.escalation.midpoint_year})`}
            value={formatUSD(est.escalation.amount_usd)}
          />
        )}
        <SubtotalRow
          label="Total estimate"
          value={formatUSD(est.total_usd)}
          strong
        />
        {est.total_per_sf_usd && (
          <SubtotalRow
            label="Per SF"
            value={`$${est.total_per_sf_usd.toFixed(2)}/SF`}
          />
        )}
        {est.total_per_mw_usd && (
          <SubtotalRow
            label="Per MW"
            value={`${formatUSD(est.total_per_mw_usd, true)}/MW`}
          />
        )}
      </div>
    </div>
  );
}

/* ── Schedule Tab ─────────────────────────────────────────────────────── */

function ScheduleTab({
  sched,
  printForceOpen,
}: {
  sched: CostSchedulePackage["metadata"]["schedule"];
  printForceOpen?: boolean;
}) {
  if (!sched) {
    return (
      <div className="text-callout text-label-secondary py-4 text-center">
        No schedule data available.
      </div>
    );
  }

  const criticalIds = new Set(sched.critical_path_ids ?? []);
  const maxDur = Math.max(...(sched.activities ?? []).map((a) => a.duration_days ?? 0), 1);

  return (
    <div className="space-y-4">
      {/* Duration summary */}
      <div className="rounded-xl bg-bg-elevated px-4 py-3">
        <div className="text-caption-1 uppercase tracking-wider text-label-tertiary mb-1">
          Total duration
        </div>
        <div className="text-title-3 font-bold text-label-primary tabular-nums">
          {sched.total_duration_days} calendar days
        </div>
        {sched.calendar_assumptions && (
          <div className="text-footnote text-label-secondary mt-1">
            {sched.calendar_assumptions}
          </div>
        )}
      </div>

      {/* Milestones */}
      {sched.milestones && sched.milestones.length > 0 && (
        <div className="rounded-xl bg-bg-elevated px-4 py-3">
          <div className="text-caption-1 uppercase tracking-wider text-label-tertiary mb-2">
            Milestones
          </div>
          <div className="space-y-1.5">
            {sched.milestones.map((m, i) => (
              <div key={m.id ?? i} className="flex items-center gap-3">
                <div className="h-2 w-2 rounded-full bg-accent shrink-0" />
                <span className="flex-1 text-callout text-label-primary">
                  {m.name}
                </span>
                {m.target_date && (
                  <span className="text-footnote text-label-tertiary tabular-nums">
                    {m.target_date}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Activities timeline — horizontal scrolling band */}
      <Section
        title={`Activities (${sched.activities?.length ?? 0})`}
        defaultOpen={true}
        printForceOpen={printForceOpen}
      >
        <div className="overflow-x-auto -mx-0 mt-1">
          <div className="min-w-[500px] space-y-1.5 py-1">
            {(sched.activities ?? []).map((act, i) => {
              const isCritical =
                act.critical_path === true || criticalIds.has(act.id);
              const barPct =
                maxDur > 0
                  ? Math.max(2, Math.round(((act.duration_days ?? 0) / maxDur) * 100))
                  : 2;

              return (
                <div
                  key={act.id ?? i}
                  className={cn(
                    "rounded-md px-3 py-2",
                    isCritical ? "bg-accent/10 border border-accent/30" : "bg-bg-tertiary",
                  )}
                >
                  <div className="flex items-center gap-2">
                    <div className="w-6 text-caption-2 text-label-tertiary font-mono shrink-0">
                      {act.wbs ?? act.id}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span
                          className={cn(
                            "text-callout truncate",
                            isCritical
                              ? "text-label-primary font-medium"
                              : "text-label-secondary",
                          )}
                        >
                          {act.name}
                        </span>
                        {act.milestone && (
                          <span className="shrink-0 rounded px-1.5 py-0.5 text-caption-2 bg-accent/15 text-accent">
                            milestone
                          </span>
                        )}
                        {isCritical && (
                          <span className="shrink-0 rounded px-1.5 py-0.5 text-caption-2 bg-danger/15 text-danger">
                            critical
                          </span>
                        )}
                      </div>
                      {/* Simple duration bar */}
                      {(act.duration_days ?? 0) > 0 && (
                        <div className="h-1.5 rounded-full bg-bg-elevated overflow-hidden">
                          <div
                            className={cn(
                              "h-full rounded-full",
                              isCritical ? "bg-danger/60" : "bg-accent/40",
                            )}
                            style={{ width: `${barPct}%` }}
                          />
                        </div>
                      )}
                    </div>
                    <div className="shrink-0 text-right">
                      <div className="text-footnote text-label-secondary tabular-nums">
                        {act.duration_days}d
                      </div>
                      {act.predecessors && act.predecessors.length > 0 && (
                        <div className="text-caption-2 text-label-tertiary tabular-nums">
                          after {act.predecessors.map((p) => p.id).join(", ")}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </Section>
    </div>
  );
}

/* ── Basis of Estimate Tab ────────────────────────────────────────────── */

function BasisTab({
  meta,
  artifact,
  printForceOpen,
}: {
  meta: CostSchedulePackage["metadata"];
  artifact: CostSchedulePackage;
  printForceOpen?: boolean;
}) {
  return (
    <div className="space-y-4">
      {meta.basis_of_estimate && (
        <Section
          title="Basis of Estimate"
          defaultOpen={true}
          printForceOpen={printForceOpen}
        >
          <MarkdownBlock content={meta.basis_of_estimate} className="pt-1" />
        </Section>
      )}
      {meta.basis_of_schedule && (
        <Section
          title="Basis of Schedule"
          defaultOpen={true}
          printForceOpen={printForceOpen}
        >
          <MarkdownBlock content={meta.basis_of_schedule} className="pt-1" />
        </Section>
      )}
      {artifact.body_markdown && (
        <Section
          title="Full narrative"
          defaultOpen={false}
          printForceOpen={printForceOpen}
        >
          <MarkdownBlock content={artifact.body_markdown} className="pt-1" />
        </Section>
      )}
      {/* Uploaded files */}
      {meta.uploaded_files?.length > 0 && (
        <Section
          title="Files reviewed"
          defaultOpen={false}
          printForceOpen={printForceOpen}
        >
          <ul className="space-y-1.5 pt-1">
            {meta.uploaded_files.map((f, i) => (
              <li key={i} className="flex items-start gap-2 text-footnote">
                <span
                  className={cn(
                    "mt-0.5 rounded px-1.5 py-0.5 text-caption-2 font-mono uppercase shrink-0",
                    f.extraction_status === "ok"
                      ? "bg-success/15 text-success"
                      : f.extraction_status === "partial"
                        ? "bg-warning/15 text-warning"
                        : "bg-danger/15 text-danger",
                  )}
                >
                  {f.extraction_status}
                </span>
                <span className="text-label-primary">{f.filename}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}
