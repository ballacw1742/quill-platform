"use client";

import * as React from "react";
import {
  Brain,
  Building2,
  ChevronDown,
  ChevronUp,
  ClipboardList,
  FolderKanban,
  MapPin,
  Package,
  TrendingUp,
  Users,
  Zap,
  Server,
  DollarSign,
  Activity,
  AlertCircle,
  CheckCircle2,
  Clock,
  RotateCcw,
} from "lucide-react";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { ErrorBanner } from "@/components/ui/error-banner";
import { useKpis, useExceptions, useBrief, useAgentActivity } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import type { KpiSnapshot, ExceptionList, Brief, AgentActivityList } from "@/lib/schemas";

/* ── KPI card ─────────────────────────────────────────────────────────────── */

type KpiColor = "green" | "yellow" | "red" | "neutral";

function kpiColorClass(color: KpiColor) {
  switch (color) {
    case "green":
      return "text-green-600";
    case "yellow":
      return "text-yellow-600";
    case "red":
      return "text-danger";
    default:
      return "text-label-primary";
  }
}

function KpiCard({
  label,
  value,
  unit,
  color = "neutral",
  trend,
}: {
  label: string;
  value: string;
  unit?: string;
  color?: KpiColor;
  trend?: "up" | "down";
}) {
  return (
    <div className="rounded-xl bg-bg-elevated px-4 py-4 flex flex-col gap-1.5">
      <span className="text-caption-1 text-label-tertiary">{label}</span>
      <div className="flex items-baseline gap-1.5">
        <span className={cn("text-title-1 font-bold tabular-nums", kpiColorClass(color))}>
          {value}
        </span>
        {trend === "up" && <span className="text-green-500 text-caption-1">↑</span>}
        {trend === "down" && <span className="text-danger text-caption-1">↓</span>}
      </div>
      {unit && <span className="text-caption-2 text-label-quaternary">{unit}</span>}
    </div>
  );
}

/* ── Section header ────────────────────────────────────────────────────────── */

function SectionHeader({ title, icon }: { title: string; icon: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent/10 text-accent">
        {icon}
      </span>
      <h2 className="text-headline font-semibold text-label-primary">{title}</h2>
    </div>
  );
}

/* ── Morning brief section ─────────────────────────────────────────────────── */

function BriefSection({ title, summary, actionItems }: {
  title: string;
  summary: string;
  actionItems: string[];
}) {
  return (
    <div className="border-b border-separator/30 last:border-0 py-3">
      <p className="text-footnote font-semibold text-label-secondary uppercase tracking-wide mb-1">
        {title}
      </p>
      <p className="text-body text-label-primary leading-relaxed">{summary}</p>
      {actionItems.length > 0 && (
        <ul className="mt-2 space-y-0.5">
          {actionItems.map((item, i) => (
            <li key={i} className="flex items-start gap-1.5 text-footnote text-label-secondary">
              <span className="mt-0.5 text-accent">→</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ── Module health card ────────────────────────────────────────────────────── */

type HealthStatus = "green" | "yellow" | "red";

function moduleHealthClass(status: HealthStatus) {
  switch (status) {
    case "green":
      return "bg-green-500";
    case "yellow":
      return "bg-yellow-500";
    case "red":
      return "bg-danger";
  }
}

function ModuleCard({
  name,
  icon,
  metrics,
  health,
}: {
  name: string;
  icon: React.ReactNode;
  metrics: string[];
  health: HealthStatus;
}) {
  return (
    <div className="rounded-xl bg-bg-elevated px-4 py-4 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-bg-primary text-label-secondary">
            {icon}
          </span>
          <span className="text-footnote font-semibold text-label-primary">{name}</span>
        </div>
        <span
          className={cn("h-2.5 w-2.5 rounded-full", moduleHealthClass(health))}
          title={`${health === "green" ? "Healthy" : health === "yellow" ? "Warning" : "Critical"}`}
        />
      </div>
      {metrics.map((m, i) => (
        <p key={i} className="text-caption-1 text-label-tertiary leading-snug">{m}</p>
      ))}
    </div>
  );
}

/* ── Activity row ──────────────────────────────────────────────────────────── */

function ActivityRow({ item }: { item: AgentActivityList["items"][number] }) {
  const isOk = item.status === "complete";
  const relTime = formatRelTime(item.created_at);
  return (
    <div className="flex items-start gap-3 py-3 border-b border-separator/30 last:border-0">
      <span className={cn("mt-0.5 shrink-0", isOk ? "text-green-500" : "text-danger")}>
        {isOk ? <CheckCircle2 className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-footnote font-medium text-label-primary capitalize">
            {item.intent}
          </span>
          <span className="text-caption-1 text-label-quaternary">{relTime}</span>
        </div>
        {item.message_preview && (
          <p className="mt-0.5 text-caption-1 text-label-tertiary truncate">
            {item.message_preview}
          </p>
        )}
      </div>
      <span
        className={cn(
          "shrink-0 rounded px-1.5 py-0.5 text-caption-2 font-medium",
          isOk ? "bg-green-500/10 text-green-700" : "bg-danger/10 text-danger",
        )}
      >
        {item.status}
      </span>
    </div>
  );
}

/* ── Main page ─────────────────────────────────────────────────────────────── */

function IntelligencePageInner() {
  const kpisQuery = useKpis();
  const exceptionsQuery = useExceptions();
  const briefQuery = useBrief();
  const activityQuery = useAgentActivity();

  const kpis = kpisQuery.data as KpiSnapshot | undefined;
  const exceptions = exceptionsQuery.data as ExceptionList | undefined;
  const brief = briefQuery.data as Brief | undefined;
  const activity = activityQuery.data as AgentActivityList | undefined;

  const [briefOpen, setBriefOpen] = React.useState(false);

  const hasError = kpisQuery.error || exceptionsQuery.error;

  // Compute module health from exceptions
  const moduleExceptionCount = React.useMemo(() => {
    const counts: Record<string, number> = {};
    for (const item of exceptions?.items ?? []) {
      counts[item.module] = (counts[item.module] ?? 0) + 1;
    }
    return counts;
  }, [exceptions]);

  const moduleHealth = (module: string): HealthStatus => {
    const count = moduleExceptionCount[module] ?? 0;
    if (count === 0) return "green";
    const hasP1 = exceptions?.items.some(
      (e) => e.module === module && (e.severity === "P1" || e.severity === "P2"),
    );
    return hasP1 ? "red" : "yellow";
  };

  // KPI color helpers
  const incidentColor: KpiColor =
    kpis && kpis.active_incidents_p1_p2 > 0 ? "red" : "green";
  const pueColor: KpiColor =
    kpis?.avg_pue == null ? "neutral" : kpis.avg_pue <= 1.4 ? "green" : kpis.avg_pue <= 1.6 ? "yellow" : "red";
  const equipColor: KpiColor =
    kpis && kpis.at_risk_equipment_count > 0 ? "yellow" : "green";
  const mwLiveColor: KpiColor = kpis && kpis.mw_live > 0 ? "green" : "neutral";

  return (
    <MobileShell>
      <TopBar
        title={
          <span className="flex items-center gap-2">
            <Brain className="h-5 w-5 text-accent" />
            Intelligence
          </span>
        }
      />

      <div className="bg-bg-elevated min-h-full overflow-y-auto">
        <div className="flex flex-col gap-6 px-4 pt-4 pb-12">
          {hasError && (
            <ErrorBanner message="Some data failed to load. Pull to refresh." />
          )}

          {/* ═══════════════════════════════════════════════════
              Section 1 — Company Scorecard
          ═══════════════════════════════════════════════════ */}
          <section>
            <SectionHeader title="Company Scorecard" icon={<Activity className="h-4 w-4" />} />

            {kpisQuery.isLoading ? (
              <div className="grid grid-cols-2 gap-3">
                {Array.from({ length: 12 }).map((_, i) => (
                  <div key={i} className="h-24 rounded-xl bg-bg-elevated animate-pulse" />
                ))}
              </div>
            ) : kpis ? (
              <div className="grid grid-cols-2 gap-3">
                {/* MW Section */}
                <KpiCard
                  label="MW Under Site Control"
                  value={kpis.mw_under_site_control.toFixed(1)}
                  unit="MW"
                  color={kpis.mw_under_site_control > 0 ? "green" : "neutral"}
                />
                <KpiCard
                  label="MW Under Construction"
                  value={kpis.mw_under_construction.toFixed(1)}
                  unit="MW"
                />
                <KpiCard
                  label="MW Live"
                  value={kpis.mw_live.toFixed(1)}
                  unit="MW"
                  color={mwLiveColor}
                />

                {/* Revenue */}
                <KpiCard
                  label="Total ARR"
                  value={formatUsdCompact(kpis.total_arr_usd)}
                  unit="Annual Recurring"
                  color={kpis.total_arr_usd > 0 ? "green" : "neutral"}
                />
                <KpiCard
                  label="Pipeline Value"
                  value={formatUsdCompact(kpis.pipeline_value_usd)}
                  unit="Active deals"
                />

                {/* Operations */}
                <KpiCard
                  label="Active Incidents"
                  value={String(kpis.active_incidents_p1_p2)}
                  unit="P1 / P2"
                  color={incidentColor}
                />
                <KpiCard
                  label="Avg PUE"
                  value={kpis.avg_pue != null ? kpis.avg_pue.toFixed(3) : "—"}
                  unit="Live campuses"
                  color={pueColor}
                />
                <KpiCard
                  label="Open Tickets"
                  value={String(kpis.open_customer_tickets)}
                  unit="Support"
                  color={kpis.open_customer_tickets > 5 ? "yellow" : "green"}
                />

                {/* Supply & Projects */}
                <KpiCard
                  label="At-Risk Equipment"
                  value={String(kpis.at_risk_equipment_count)}
                  unit="Items"
                  color={equipColor}
                />
                <KpiCard
                  label="Sites in Pipeline"
                  value={String(kpis.sites_in_pipeline)}
                  unit="Active phases"
                />
                <KpiCard
                  label="Active Projects"
                  value={String(kpis.active_projects)}
                  unit="Projects"
                  color={kpis.active_projects > 0 ? "green" : "neutral"}
                />
                <KpiCard
                  label="Active Customers"
                  value={String(kpis.active_customers)}
                  unit="Accounts"
                  color={kpis.active_customers > 0 ? "green" : "neutral"}
                />
              </div>
            ) : null}

            {kpis && (
              <p className="mt-2 text-caption-2 text-label-quaternary text-right">
                Computed {formatRelTime(kpis.computed_at)}
              </p>
            )}
          </section>

          {/* ═══════════════════════════════════════════════════
              Section 2 — Morning Brief
          ═══════════════════════════════════════════════════ */}
          <section>
            <button
              type="button"
              onClick={() => setBriefOpen((v) => !v)}
              className="w-full flex items-center justify-between mb-3 no-tap-highlight"
              aria-expanded={briefOpen}
            >
              <div className="flex items-center gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent/10 text-accent">
                  <Clock className="h-4 w-4" />
                </span>
                <h2 className="text-headline font-semibold text-label-primary">Morning Brief</h2>
              </div>
              {briefOpen ? (
                <ChevronUp className="h-5 w-5 text-label-tertiary" />
              ) : (
                <ChevronDown className="h-5 w-5 text-label-tertiary" />
              )}
            </button>

            {briefOpen && (
              <div className="rounded-2xl bg-bg-primary px-4 py-2">
                {briefQuery.isLoading ? (
                  <div className="py-6 text-footnote text-label-tertiary text-center">
                    Generating brief…
                  </div>
                ) : brief ? (
                  <>
                    <BriefSection
                      title="Incidents"
                      summary={brief.incidents.summary}
                      actionItems={brief.incidents.action_items}
                    />
                    <BriefSection
                      title="Revenue"
                      summary={brief.revenue.summary}
                      actionItems={brief.revenue.action_items}
                    />
                    <BriefSection
                      title="Construction"
                      summary={brief.construction.summary}
                      actionItems={brief.construction.action_items}
                    />
                    <BriefSection
                      title="Sites"
                      summary={brief.sites.summary}
                      actionItems={brief.sites.action_items}
                    />
                    <BriefSection
                      title="Customers"
                      summary={brief.customers.summary}
                      actionItems={brief.customers.action_items}
                    />
                    <BriefSection
                      title="Supply Chain"
                      summary={brief.supply_chain.summary}
                      actionItems={brief.supply_chain.action_items}
                    />
                    <BriefSection
                      title="Action Items"
                      summary={brief.action_items.summary}
                      actionItems={brief.action_items.action_items}
                    />
                    <p className="text-caption-2 text-label-quaternary text-right py-2">
                      Generated {formatRelTime(brief.generated_at)}
                    </p>
                  </>
                ) : (
                  <p className="py-4 text-footnote text-label-tertiary text-center">
                    Failed to load brief. Try refreshing.
                  </p>
                )}
              </div>
            )}
          </section>

          {/* ═══════════════════════════════════════════════════
              Section 3 — Module Health Grid
          ═══════════════════════════════════════════════════ */}
          <section>
            <SectionHeader title="Module Health" icon={<Zap className="h-4 w-4" />} />
            <div className="grid grid-cols-2 gap-3">
              <ModuleCard
                name="Sites"
                icon={<MapPin className="h-4 w-4" />}
                metrics={[
                  kpis ? `${kpis.sites_in_pipeline} in pipeline` : "—",
                  `${moduleExceptionCount["SITES"] ?? 0} exception(s)`,
                ]}
                health={moduleHealth("SITES")}
              />
              <ModuleCard
                name="Projects"
                icon={<FolderKanban className="h-4 w-4" />}
                metrics={[
                  kpis ? `${kpis.active_projects} active` : "—",
                  `${moduleExceptionCount["PROJECTS"] ?? 0} exception(s)`,
                ]}
                health={moduleHealth("PROJECTS")}
              />
              <ModuleCard
                name="Operations"
                icon={<Building2 className="h-4 w-4" />}
                metrics={[
                  kpis ? `${kpis.mw_live.toFixed(1)} MW live` : "—",
                  kpis?.avg_pue ? `${kpis.avg_pue.toFixed(3)} avg PUE` : "No PUE data",
                ]}
                health={moduleHealth("OPERATIONS")}
              />
              <ModuleCard
                name="Pipeline"
                icon={<TrendingUp className="h-4 w-4" />}
                metrics={[
                  kpis ? `${formatUsdCompact(kpis.total_arr_usd)} ARR` : "—",
                  kpis ? `${formatUsdCompact(kpis.pipeline_value_usd)} pipeline` : "—",
                ]}
                health={moduleHealth("SALES")}
              />
              <ModuleCard
                name="Customers"
                icon={<Users className="h-4 w-4" />}
                metrics={[
                  kpis ? `${kpis.active_customers} accounts` : "—",
                  kpis ? `${kpis.open_customer_tickets} open tickets` : "—",
                ]}
                health={moduleHealth("CUSTOMERS")}
              />
              <ModuleCard
                name="Supply Chain"
                icon={<Package className="h-4 w-4" />}
                metrics={[
                  kpis ? `${kpis.at_risk_equipment_count} at risk` : "—",
                  `${moduleExceptionCount["SUPPLY CHAIN"] ?? 0} exception(s)`,
                ]}
                health={moduleHealth("SUPPLY CHAIN")}
              />
              <ModuleCard
                name="Contracts"
                icon={<ClipboardList className="h-4 w-4" />}
                metrics={[
                  `${moduleExceptionCount["FINANCE"] ?? 0} stale approvals`,
                ]}
                health={moduleHealth("FINANCE")}
              />
              <ModuleCard
                name="Finance"
                icon={<DollarSign className="h-4 w-4" />}
                metrics={[
                  `${moduleExceptionCount["FINANCE"] ?? 0} exception(s)`,
                ]}
                health={moduleHealth("FINANCE")}
              />
            </div>
          </section>

          {/* ═══════════════════════════════════════════════════
              Section 4 — Agent Activity Feed
          ═══════════════════════════════════════════════════ */}
          <section>
            <SectionHeader title="Agent Activity (24h)" icon={<RotateCcw className="h-4 w-4" />} />
            <div className="rounded-2xl bg-bg-primary px-4 py-2">
              {activityQuery.isLoading ? (
                <div className="py-6 text-footnote text-label-tertiary text-center">
                  Loading activity…
                </div>
              ) : !activity || activity.items.length === 0 ? (
                <div className="flex flex-col items-center gap-2 px-4 py-6">
                  <Server className="h-8 w-8 text-label-quaternary" />
                  <p className="text-footnote text-label-secondary text-center">
                    No agent activity in the last 24 hours.
                  </p>
                </div>
              ) : (
                <>
                  {activity.items.slice(0, 20).map((item) => (
                    <ActivityRow key={item.id} item={item} />
                  ))}
                  {activity.total > 20 && (
                    <p className="py-3 text-center text-caption-1 text-label-tertiary">
                      Showing 20 of {activity.total} requests
                    </p>
                  )}
                </>
              )}
            </div>
          </section>
        </div>
      </div>
    </MobileShell>
  );
}

/* ── Helpers ─────────────────────────────────────────────────────────────── */

function formatRelTime(isoStr: string): string {
  try {
    const delta = (Date.now() - new Date(isoStr).getTime()) / 1000;
    if (delta < 60) return "just now";
    if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
    if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
    return `${Math.floor(delta / 86400)}d ago`;
  } catch {
    return "";
  }
}

function formatUsdCompact(v: number): string {
  if (v >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(1)}B`;
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
  return `$${v.toFixed(0)}`;
}

export default function IntelligencePage() {
  return (
    <ErrorBoundary moduleName="Intelligence">
      <IntelligencePageInner />
    </ErrorBoundary>
  );
}
