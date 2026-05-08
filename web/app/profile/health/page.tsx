"use client";

import * as React from "react";
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronRight,
  DollarSign,
  Inbox,
  Server,
  ShieldCheck,
} from "lucide-react";
import { MobileShell, TopBar, BackButton } from "@/components/layout/MobileShell";
import { GroupedList, ListGroup } from "@/components/ui/grouped-list";
import { ListRow } from "@/components/ui/list-row";
import { useHealth } from "@/lib/api";
import type { Health } from "@/lib/schemas";
import { formatCurrency, formatPercent, cn } from "@/lib/utils";

/**
 * /profile/health — replaces /health.
 *
 * MOBILE_UX_SPEC.md §"/profile/health":
 *   - Big status hero card up top: green/yellow/red dot + headline.
 *   - List of subsystems: queue depth, audit chain, anthropic api,
 *     on-prem inference (n/a), spend MTD with progress bar.
 */

export default function ProfileHealthPage() {
  const { data: rawData, isLoading } = useHealth();
  const data = rawData as Health | undefined;

  const status = computeStatus(data);

  return (
    <MobileShell>
      <TopBar
        title="Fleet health"
        left={<BackButton href="/profile" label="Profile" />}
      />

      <GroupedList>
        {/* Hero — overall status */}
        <section className="overflow-hidden rounded-xl bg-bg-tertiary shadow-card">
          <div className="flex items-start gap-3 p-4">
            <div
              className={cn(
                "flex h-12 w-12 shrink-0 items-center justify-center rounded-full",
                status.tone === "success" && "bg-success/10 text-success",
                status.tone === "warning" && "bg-warning/10 text-warning",
                status.tone === "danger" && "bg-danger/10 text-danger",
              )}
              aria-hidden="true"
            >
              <CheckCircle2 className="h-7 w-7" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-title-3 text-label-primary">
                {status.headline}
              </div>
              <div className="text-callout text-label-secondary">
                {data?.checked_at ? (
                  `Updated ${new Date(data.checked_at).toLocaleTimeString()}`
                ) : isLoading ? (
                  <span
                    className="inline-block h-3 w-24 rounded-sm bg-bg-elevated animate-shimmer align-middle"
                    aria-label="Loading"
                  />
                ) : (
                  "—"
                )}
              </div>
            </div>
          </div>
        </section>

        {data && (
          <>
            {/* Subsystems */}
            <ListGroup title="Subsystems">
              <ListRow
                icon={<Inbox className="h-4 w-4" />}
                iconTone="info"
                title="Queue depth"
                subtitle={`Mandatory ${data.queue_depth["tier-0-mandatory"]} · Spot-check ${data.queue_depth["tier-1-spotcheck"]} · Auto ${data.queue_depth["tier-2-auto"]}`}
                href="/queue"
              />
              <ListRow
                icon={<ShieldCheck className="h-4 w-4" />}
                iconTone={data.audit_chain.ok ? "success" : "danger"}
                title="Activity log"
                subtitle={
                  data.audit_chain.ok
                    ? `Verified · ${data.audit_chain.verified} / ${data.audit_chain.total} entries`
                    : `Drift · broken at ${data.audit_chain.broken_at}`
                }
                href="/audit"
              />
              <ListRow
                icon={<Server className="h-4 w-4" />}
                iconTone={
                  data.routing.anthropic === "ok"
                    ? "success"
                    : data.routing.anthropic === "degraded"
                      ? "warning"
                      : "danger"
                }
                title="Anthropic API"
                subtitle={String(data.routing.anthropic)}
                chevron={false}
                hideDivider={false}
              />
              <ListRow
                icon={<Server className="h-4 w-4" />}
                iconTone="neutral"
                title="On-prem inference"
                subtitle={String(data.routing.on_prem)}
                chevron={false}
                hideDivider
              />
            </ListGroup>

            {/* Spend */}
            <ListGroup title="Spend">
              <div className="px-4 py-3">
                <div className="flex items-center gap-3 mb-2">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-info/10 text-info">
                    <DollarSign className="h-4 w-4" />
                  </span>
                  <div className="flex-1">
                    <div className="text-headline text-label-primary">
                      Month-to-date
                    </div>
                    <div className="text-footnote text-label-secondary">
                      {formatCurrency(data.spend.mtd_usd)} of{" "}
                      {formatCurrency(data.spend.monthly_budget_usd)}{" "}
                      ({formatPercent(
                        data.spend.mtd_usd / Math.max(1, data.spend.monthly_budget_usd),
                      )})
                    </div>
                  </div>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-bg-elevated">
                  <div
                    className={
                      data.spend.mtd_usd / data.spend.monthly_budget_usd < 0.7
                        ? "h-full bg-success"
                        : data.spend.mtd_usd / data.spend.monthly_budget_usd < 0.9
                          ? "h-full bg-warning"
                          : "h-full bg-danger"
                    }
                    style={{
                      width: `${Math.min(
                        100,
                        (data.spend.mtd_usd /
                          Math.max(1, data.spend.monthly_budget_usd)) *
                          100,
                      )}%`,
                    }}
                  />
                </div>
                <div className="mt-2 text-footnote text-label-tertiary">
                  Yesterday: {formatCurrency(data.spend.yesterday_usd)}
                </div>
              </div>
            </ListGroup>

            {/* Stats row */}
            <ListGroup title="Counters">
              <ListRow
                icon={<AlertTriangle className="h-4 w-4" />}
                iconTone={
                  data.errors_24h > 5
                    ? "danger"
                    : data.errors_24h > 0
                      ? "warning"
                      : "success"
                }
                title="Errors (24h)"
                chip={String(data.errors_24h)}
                chevron={false}
              />
              <ListRow
                icon={<Bot className="h-4 w-4" />}
                iconTone={
                  data.agents_available === data.agents_total
                    ? "success"
                    : "warning"
                }
                title="Agents available"
                chip={`${data.agents_available} / ${data.agents_total}`}
                chevron={false}
              />
              <ListRow
                icon={<Activity className="h-4 w-4" />}
                iconTone="info"
                title="SLA breaches"
                chip={String((data as { sla_breaches_open?: number }).sla_breaches_open ?? 0)}
                chevron={false}
                hideDivider
              />
            </ListGroup>
          </>
        )}
      </GroupedList>
    </MobileShell>
  );
}

function computeStatus(data: Health | undefined): {
  tone: "success" | "warning" | "danger";
  headline: string;
} {
  if (!data) return { tone: "warning", headline: "Loading status…" };
  if (!data.audit_chain?.ok) {
    return { tone: "danger", headline: "Activity log drift" };
  }
  if ((data.errors_24h ?? 0) > 5) {
    return { tone: "danger", headline: "Issues detected" };
  }
  if ((data.errors_24h ?? 0) > 0) {
    return { tone: "warning", headline: "Degraded" };
  }
  if (data.routing.anthropic === "down") {
    return { tone: "danger", headline: "Anthropic API down" };
  }
  if (data.routing.anthropic === "degraded") {
    return { tone: "warning", headline: "Degraded — model API" };
  }
  return { tone: "success", headline: "All systems normal" };
}
