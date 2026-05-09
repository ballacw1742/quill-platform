"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { Download } from "lucide-react";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { useEstimateExport } from "@/lib/api";
import {
  CostSchedulePackageSchema,
  type CostSchedulePackage,
  type EstimateRow,
  type RiskItem,
} from "@/lib/schemas";
import { cn } from "@/lib/utils";

const GanttChart = dynamic(
  () => import("./GanttChart").then((m) => m.GanttChart),
  { ssr: false },
);

type Tab = "estimate" | "schedule" | "risks" | "basis" | "next";

export function EstimatePackageDetail({
  metadata,
}: {
  metadata: Record<string, unknown> | null | undefined;
}) {
  const parsed = React.useMemo(() => {
    if (!metadata) return null;
    const result = CostSchedulePackageSchema.safeParse({
      artifact_type: "cost_schedule_package",
      title: "",
      summary: "",
      body_markdown: "",
      metadata,
      confidence: 0,
    });
    return result.success ? result.data : null;
  }, [metadata]);

  if (!parsed) {
    return (
      <div className="rounded-md bg-warning/10 px-3 py-2 text-callout text-warning">
        We couldn&apos;t parse the package metadata. Showing raw markdown only.
      </div>
    );
  }

  return <EstimatePackageDetailInner pkg={parsed} />;
}

function EstimatePackageDetailInner({ pkg }: { pkg: CostSchedulePackage }) {
  const m = pkg.metadata;
  const [tab, setTab] = React.useState<Tab>("estimate");

  const exportCsv = useEstimateExport(m.upload_id ?? null, "csv");
  const exportXer = useEstimateExport(m.upload_id ?? null, "xer");

  const totalDuration =
    m.headline_metrics?.total_duration_days ?? m.schedule.total_duration_days ?? 0;
  const total = m.estimate.total_usd ?? 0;
  const perSf = m.estimate.total_per_sf_usd ?? m.headline_metrics?.total_per_sf_usd;
  const perMw = m.estimate.total_per_mw_usd ?? m.headline_metrics?.total_per_mw_usd;

  return (
    <div className="flex flex-col gap-4">
      {/* Hero metrics */}
      <section className="rounded-xl bg-bg-tertiary p-4 shadow-card">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <ClassBadge cls={m.aace_class} />
          <span className="inline-flex items-center rounded-md bg-info/10 px-2 py-0.5 text-caption-1 font-medium text-info">
            Schedule level {m.schedule_level}
          </span>
          <span className="inline-flex items-center rounded-md bg-bg-elevated px-2 py-0.5 text-caption-1 text-label-secondary">
            Library {m.library_version || "—"}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Metric
            label="Total"
            value={formatUsd(total)}
            tone="primary"
          />
          <Metric
            label="Duration"
            value={`${totalDuration} d`}
            tone="primary"
          />
          <Metric
            label="$/SF"
            value={perSf != null ? formatUsd(perSf) : "—"}
          />
          <Metric
            label="$/MW"
            value={perMw != null ? formatUsd(perMw) : "—"}
          />
        </div>
      </section>

      {/* Tabs */}
      <SegmentedControl<Tab>
        value={tab}
        onChange={setTab}
        ariaLabel="Estimate package sections"
        options={[
          { value: "estimate", label: "Estimate" },
          { value: "schedule", label: "Schedule" },
          { value: "risks", label: "Risks" },
          { value: "basis", label: "Basis" },
          { value: "next", label: "Next class" },
        ]}
      />

      {tab === "estimate" && (
        <EstimateTab pkg={pkg} onExportCsv={() => exportCsv()} canExport={!!m.upload_id} />
      )}
      {tab === "schedule" && (
        <ScheduleTab pkg={pkg} onExportXer={() => exportXer()} canExport={!!m.upload_id && (m.schedule_level ?? 1) >= 3} />
      )}
      {tab === "risks" && <RisksTab pkg={pkg} />}
      {tab === "basis" && <BasisTab pkg={pkg} />}
      {tab === "next" && <NextClassTab pkg={pkg} />}
    </div>
  );
}

/* ── Tabs ───────────────────────────────────────────────────────────────── */

type EstimateRowSort = "csi" | "extended_desc" | "extended_asc";

function EstimateTab({
  pkg,
  onExportCsv,
  canExport,
}: {
  pkg: CostSchedulePackage;
  onExportCsv: () => void;
  canExport: boolean;
}) {
  const m = pkg.metadata;
  const [sort, setSort] = React.useState<EstimateRowSort>("csi");

  const grouped = React.useMemo(() => groupByCsi(m.estimate.rows, sort), [m.estimate.rows, sort]);

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-footnote text-label-tertiary">Sort</span>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as EstimateRowSort)}
            className="rounded-md bg-bg-elevated px-2 py-1 text-footnote text-label-primary"
          >
            <option value="csi">CSI section</option>
            <option value="extended_desc">$ — high to low</option>
            <option value="extended_asc">$ — low to high</option>
          </select>
        </div>
        <button
          type="button"
          disabled={!canExport}
          onClick={onExportCsv}
          className={cn(
            "inline-flex items-center gap-1 rounded-md bg-bg-elevated px-3 py-1.5 text-footnote text-accent active:opacity-70 no-tap-highlight",
            !canExport && "opacity-50 pointer-events-none",
          )}
        >
          <Download className="h-3.5 w-3.5" />
          Export CSV
        </button>
      </div>

      <div className="overflow-x-auto rounded-md border border-separator/40">
        <table className="w-full min-w-[520px] text-footnote">
          <thead className="bg-bg-tertiary text-label-secondary">
            <tr>
              <th className="px-3 py-2 text-left font-medium">CSI</th>
              <th className="px-3 py-2 text-left font-medium">Description</th>
              <th className="px-3 py-2 text-right font-medium">Qty</th>
              <th className="px-3 py-2 text-right font-medium">Rate</th>
              <th className="px-3 py-2 text-right font-medium">Extended</th>
            </tr>
          </thead>
          <tbody>
            {grouped.map(([section, rows]) => (
              <React.Fragment key={section}>
                <tr className="bg-bg-elevated/40">
                  <td colSpan={5} className="px-3 py-1.5 text-caption-1 font-medium text-label-secondary">
                    {section}
                  </td>
                </tr>
                {rows.map((r, i) => (
                  <tr
                    key={`${section}-${i}`}
                    className="border-t border-separator/40 align-top"
                  >
                    <td className="px-3 py-2 tabular-nums text-label-secondary">{r.csi_section}</td>
                    <td className="px-3 py-2 text-label-primary">
                      <div>{r.description}</div>
                      {r.notes && (
                        <div className="text-caption-1 text-label-tertiary">{r.notes}</div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {formatNum(r.quantity)} {r.unit}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatUsd(r.unit_rate_usd)}</td>
                    <td className="px-3 py-2 text-right tabular-nums font-medium">
                      {formatUsd(r.extended_usd)}
                    </td>
                  </tr>
                ))}
              </React.Fragment>
            ))}
            {/* Totals */}
            <tr className="border-t border-separator/40 bg-bg-tertiary">
              <td colSpan={4} className="px-3 py-2 text-right font-medium">Subtotal — direct</td>
              <td className="px-3 py-2 text-right font-medium tabular-nums">
                {formatUsd(m.estimate.subtotal_direct_usd)}
              </td>
            </tr>
            {m.estimate.indirects.map((ind, i) => (
              <tr key={`ind-${i}`} className="border-t border-separator/40">
                <td colSpan={4} className="px-3 py-2 text-right text-label-secondary">
                  {ind.label}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{formatUsd(ind.amount_usd)}</td>
              </tr>
            ))}
            {m.estimate.contingency && (
              <tr className="border-t border-separator/40">
                <td colSpan={4} className="px-3 py-2 text-right text-label-secondary">
                  Contingency ({m.estimate.contingency.pct_of_direct_plus_indirect}%)
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {formatUsd(m.estimate.contingency.amount_usd)}
                </td>
              </tr>
            )}
            {m.estimate.escalation && (
              <tr className="border-t border-separator/40">
                <td colSpan={4} className="px-3 py-2 text-right text-label-secondary">
                  Escalation ({m.estimate.escalation.annual_pct}%/yr → {m.estimate.escalation.midpoint_year})
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {formatUsd(m.estimate.escalation.amount_usd)}
                </td>
              </tr>
            )}
            <tr className="border-t-2 border-separator bg-bg-tertiary">
              <td colSpan={4} className="px-3 py-2 text-right font-semibold">Total</td>
              <td className="px-3 py-2 text-right font-semibold tabular-nums">
                {formatUsd(m.estimate.total_usd)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ScheduleTab({
  pkg,
  onExportXer,
  canExport,
}: {
  pkg: CostSchedulePackage;
  onExportXer: () => void;
  canExport: boolean;
}) {
  const m = pkg.metadata;
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="text-footnote text-label-tertiary">
          Level {m.schedule_level} · {m.schedule.activities.length} activities ·{" "}
          {m.schedule.total_duration_days} days
        </div>
        <button
          type="button"
          disabled={!canExport}
          onClick={onExportXer}
          title={
            !canExport
              ? "P6 XER export is available for Class 3+ schedules (Level 3 and up)."
              : undefined
          }
          className={cn(
            "inline-flex items-center gap-1 rounded-md bg-bg-elevated px-3 py-1.5 text-footnote text-accent active:opacity-70 no-tap-highlight",
            !canExport && "opacity-50 pointer-events-none",
          )}
        >
          <Download className="h-3.5 w-3.5" />
          Export P6 XER
        </button>
      </div>
      <GanttChart schedule={m.schedule} />
      {m.schedule.calendar_assumptions && (
        <p className="text-footnote text-label-tertiary">
          {m.schedule.calendar_assumptions}
        </p>
      )}
    </section>
  );
}

type RiskSort = "severity" | "likelihood" | "impact_high";

function RisksTab({ pkg }: { pkg: CostSchedulePackage }) {
  const m = pkg.metadata;
  const [sort, setSort] = React.useState<RiskSort>("severity");
  const sorted = React.useMemo(
    () => sortRisks(m.risk_register, sort),
    [m.risk_register, sort],
  );
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="text-footnote text-label-tertiary">
          {m.risk_register.length} risks
        </div>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as RiskSort)}
          className="rounded-md bg-bg-elevated px-2 py-1 text-footnote text-label-primary"
        >
          <option value="severity">Severity (likelihood × impact)</option>
          <option value="likelihood">Likelihood</option>
          <option value="impact_high">Highest $ impact</option>
        </select>
      </div>
      <ul className="flex flex-col gap-2">
        {sorted.map((r) => (
          <li key={r.id} className="rounded-md bg-bg-tertiary p-3">
            <div className="flex items-center gap-2 flex-wrap">
              <LikelihoodChip likelihood={r.likelihood} />
              <span className="inline-flex items-center rounded-sm bg-bg-elevated px-2 py-0.5 text-caption-1 text-label-secondary">
                {r.category}
              </span>
              {r.owner_role && (
                <span className="ml-auto text-footnote text-label-tertiary">
                  Owner: {r.owner_role}
                </span>
              )}
            </div>
            <div className="mt-2 text-callout text-label-primary">
              {r.description}
            </div>
            {(r.impact_usd_low != null || r.impact_usd_high != null) && (
              <div className="mt-1 text-footnote text-label-tertiary tabular-nums">
                {formatUsd(r.impact_usd_low ?? 0)} – {formatUsd(r.impact_usd_high ?? 0)}
                {(r.schedule_impact_days_low != null || r.schedule_impact_days_high != null) && (
                  <>
                    {" · "}
                    {r.schedule_impact_days_low ?? 0}–{r.schedule_impact_days_high ?? 0} days
                  </>
                )}
              </div>
            )}
            {r.mitigation && (
              <div className="mt-2 text-footnote text-label-secondary">
                Mitigation: {r.mitigation}
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function BasisTab({ pkg }: { pkg: CostSchedulePackage }) {
  const m = pkg.metadata;
  return (
    <section className="flex flex-col gap-4">
      <Prose title="Basis of estimate">{m.basis_of_estimate}</Prose>
      <Prose title="Basis of schedule">{m.basis_of_schedule}</Prose>
      {m.estimate.contingency?.rationale && (
        <Prose title="Contingency rationale">{m.estimate.contingency.rationale}</Prose>
      )}
    </section>
  );
}

function NextClassTab({ pkg }: { pkg: CostSchedulePackage }) {
  const m = pkg.metadata;
  if (m.missing_info_to_next_class.length === 0) {
    return (
      <div className="rounded-md bg-success/10 p-3 text-callout text-success">
        Nothing flagged. The estimator says the design supports the current
        class without obvious gaps.
      </div>
    );
  }
  return (
    <section className="flex flex-col gap-2">
      {m.missing_info_to_next_class.map((it, i) => (
        <div key={i} className="rounded-md bg-bg-tertiary p-3">
          <div className="flex items-baseline gap-2">
            <span className="inline-flex items-center rounded-sm bg-accent/10 px-1.5 py-0.5 text-caption-1 font-medium text-accent">
              Unlocks Class {it.would_unlock_class}
            </span>
            <span className="text-headline text-label-primary">{it.deliverable}</span>
          </div>
          <p className="mt-1 text-footnote text-label-secondary">{it.rationale}</p>
          {it.estimated_cost_to_complete_usd != null && (
            <div className="mt-1 text-footnote text-label-tertiary tabular-nums">
              Cost to complete: {formatUsd(it.estimated_cost_to_complete_usd)}
            </div>
          )}
        </div>
      ))}
    </section>
  );
}

/* ── Sub-components ─────────────────────────────────────────────────────── */

function ClassBadge({ cls }: { cls: string }) {
  return (
    <span className="inline-flex items-center rounded-md bg-accent px-2.5 py-1 text-headline font-semibold text-white">
      Class {cls}
    </span>
  );
}

function Metric({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "primary" | "neutral";
}) {
  return (
    <div>
      <div className="text-caption-1 text-label-tertiary uppercase tracking-wide">{label}</div>
      <div
        className={cn(
          "mt-0.5 tabular-nums",
          tone === "primary" ? "text-title-3 text-label-primary" : "text-headline text-label-secondary",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function Prose({ title, children }: { title: string; children: React.ReactNode }) {
  if (!children || (typeof children === "string" && children.trim() === "")) {
    return null;
  }
  return (
    <div className="rounded-md bg-bg-tertiary p-3">
      <div className="text-headline text-label-primary">{title}</div>
      <p className="mt-1.5 whitespace-pre-wrap text-callout text-label-secondary">
        {children}
      </p>
    </div>
  );
}

function LikelihoodChip({ likelihood }: { likelihood: string }) {
  const tone =
    likelihood === "high"
      ? "bg-danger/10 text-danger"
      : likelihood === "medium"
        ? "bg-warning/10 text-warning"
        : "bg-success/10 text-success";
  return (
    <span className={cn("inline-flex items-center rounded-sm px-2 py-0.5 text-caption-1 font-medium", tone)}>
      {likelihood}
    </span>
  );
}

/* ── Helpers ────────────────────────────────────────────────────────────── */

function formatUsd(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);
}
function formatNum(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(n);
}

function groupByCsi(
  rows: EstimateRow[],
  sort: EstimateRowSort,
): Array<[string, EstimateRow[]]> {
  const sorted = [...rows];
  if (sort === "extended_desc") {
    sorted.sort((a, b) => (b.extended_usd ?? 0) - (a.extended_usd ?? 0));
    return [["All rows", sorted]];
  }
  if (sort === "extended_asc") {
    sorted.sort((a, b) => (a.extended_usd ?? 0) - (b.extended_usd ?? 0));
    return [["All rows", sorted]];
  }
  // CSI grouping: bucket by first 2 digits.
  const map = new Map<string, EstimateRow[]>();
  for (const r of sorted) {
    const key = (r.csi_section || "00 00 00").slice(0, 2);
    const label = csiDivisionLabel(key);
    const list = map.get(label) ?? [];
    list.push(r);
    map.set(label, list);
  }
  return Array.from(map.entries()).sort((a, b) => a[0].localeCompare(b[0]));
}

function csiDivisionLabel(twoDigit: string): string {
  const labels: Record<string, string> = {
    "01": "01 — General requirements",
    "02": "02 — Existing conditions",
    "03": "03 — Concrete",
    "04": "04 — Masonry",
    "05": "05 — Metals",
    "06": "06 — Wood, plastics, composites",
    "07": "07 — Thermal & moisture",
    "08": "08 — Openings",
    "09": "09 — Finishes",
    "10": "10 — Specialties",
    "11": "11 — Equipment",
    "12": "12 — Furnishings",
    "13": "13 — Special construction",
    "14": "14 — Conveying equipment",
    "21": "21 — Fire suppression",
    "22": "22 — Plumbing",
    "23": "23 — HVAC",
    "25": "25 — Integrated automation",
    "26": "26 — Electrical",
    "27": "27 — Communications",
    "28": "28 — Electronic safety & security",
    "31": "31 — Earthwork",
    "32": "32 — Exterior improvements",
    "33": "33 — Utilities",
    "34": "34 — Transportation",
    "35": "35 — Waterway/marine",
    "40": "40 — Process integration",
    "41": "41 — Material processing",
    "42": "42 — Process heating/cooling",
    "43": "43 — Process gas/liquid handling",
    "44": "44 — Pollution control",
    "45": "45 — Industry-specific",
    "46": "46 — Water/wastewater equipment",
    "48": "48 — Electrical power generation",
  };
  return labels[twoDigit] ?? `Division ${twoDigit}`;
}

function sortRisks(rows: RiskItem[], sort: RiskSort): RiskItem[] {
  const lScore = (l: string) => (l === "high" ? 3 : l === "medium" ? 2 : 1);
  const out = [...rows];
  if (sort === "likelihood") {
    out.sort((a, b) => lScore(b.likelihood) - lScore(a.likelihood));
  } else if (sort === "impact_high") {
    out.sort((a, b) => (b.impact_usd_high ?? 0) - (a.impact_usd_high ?? 0));
  } else {
    out.sort((a, b) => {
      const sa = lScore(a.likelihood) * (a.impact_usd_high ?? 0);
      const sb = lScore(b.likelihood) * (b.impact_usd_high ?? 0);
      return sb - sa;
    });
  }
  return out;
}

/* ── AACE classification simple variant (re-exported for reuse) ─────────── */

export function AaceClassificationDetail({
  metadata,
}: {
  metadata: Record<string, unknown> | null | undefined;
}) {
  const cls = (metadata?.class as string | undefined) ?? "—";
  const maturity =
    (metadata?.design_maturity_estimate_pct as number | undefined) ?? 0;
  const evidence =
    ((metadata?.supporting_evidence as Array<{
      category: string;
      score: number;
      evidence: string;
    }>) ?? []) || [];
  const missing =
    ((metadata?.missing_for_next_class as Array<{
      deliverable: string;
      rationale: string;
      would_unlock_class: string;
    }>) ?? []) || [];
  const uploadId = metadata?.upload_id as string | undefined;

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-xl bg-bg-tertiary p-4 shadow-card">
        <div className="flex items-baseline gap-2">
          <ClassBadge cls={cls} />
          <span className="text-callout text-label-secondary">
            {Math.round(maturity)}% design maturity
          </span>
        </div>
        {evidence.length > 0 && (
          <div className="mt-4">
            <div className="text-headline text-label-primary mb-2">
              Why this class
            </div>
            <ul className="flex flex-col gap-1.5">
              {evidence.slice(0, 12).map((e, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="mt-0.5 inline-block h-2 w-12 shrink-0 rounded-full bg-bg-elevated overflow-hidden">
                    <span
                      className="block h-full bg-accent"
                      style={{ width: `${Math.round((e.score || 0) * 100)}%` }}
                    />
                  </span>
                  <span className="text-footnote text-label-secondary">
                    <span className="text-label-primary">
                      {e.category.replace(/_/g, " ")}.
                    </span>{" "}
                    {e.evidence}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {missing.length > 0 && (
        <section className="rounded-xl bg-bg-tertiary p-4 shadow-card">
          <div className="text-headline text-label-primary mb-2">
            To unlock the next class
          </div>
          <ul className="flex flex-col gap-1.5">
            {missing.map((m, i) => (
              <li key={i} className="text-footnote text-label-secondary">
                <span className="text-label-primary">{m.deliverable}.</span>{" "}
                {m.rationale}{" "}
                <span className="text-label-tertiary">
                  (Class {m.would_unlock_class})
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {uploadId && (
        <a
          href={`/estimates/${encodeURIComponent(uploadId)}`}
          className="inline-flex items-center justify-center rounded-md bg-accent px-4 py-2 text-headline text-white active:opacity-85 no-tap-highlight"
        >
          Generate estimate
        </a>
      )}
    </div>
  );
}
