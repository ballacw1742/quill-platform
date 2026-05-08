"use client";

import * as React from "react";
import { Activity, AlertTriangle, Bot, DollarSign, Server } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { HashChainVerifier } from "@/components/audit/HashChainVerifier";
import { useHealth } from "@/lib/api";
import { formatCurrency, formatPercent } from "@/lib/utils";
import { LANE_META } from "@/components/queue/laneMeta";

const STATUS_TONE: Record<string, "success" | "warning" | "destructive" | "muted"> = {
  ok: "success",
  degraded: "warning",
  down: "destructive",
  "n/a": "muted",
};

export default function HealthPage() {
  const { data, isLoading } = useHealth();

  if (isLoading || !data) {
    return (
      <AppShell>
        <div className="container mx-auto max-w-[1400px] px-3 py-4 md:px-6">
          <Skeleton className="h-72 w-full" />
        </div>
      </AppShell>
    );
  }

  const totalQueue =
    data.queue_depth["tier-0-mandatory"] +
    data.queue_depth["tier-1-spotcheck"] +
    data.queue_depth["tier-2-auto"];
  const spendPct = data.spend.mtd_usd / data.spend.monthly_budget_usd;

  return (
    <AppShell>
      <div className="container mx-auto flex max-w-[1400px] flex-col gap-4 px-3 py-4 md:px-6">
        <div className="flex items-center gap-2">
          <Activity className="h-5 w-5" />
          <h1 className="text-lg font-semibold tracking-tight">Fleet health</h1>
          <span className="ml-auto text-xs text-muted-foreground">
            Updated {new Date(data.checked_at).toLocaleTimeString()}
          </span>
        </div>

        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <StatCard
            icon={<Activity className="h-4 w-4" />}
            label="Total pending"
            value={String(totalQueue)}
            sub={`Tier 0/1/2 · ${data.queue_depth["tier-0-mandatory"]}/${data.queue_depth["tier-1-spotcheck"]}/${data.queue_depth["tier-2-auto"]}`}
          />
          <StatCard
            icon={<AlertTriangle className="h-4 w-4" />}
            label="Errors (24h)"
            value={String(data.errors_24h)}
            tone={data.errors_24h > 5 ? "destructive" : data.errors_24h > 0 ? "warning" : "success"}
          />
          <StatCard
            icon={<Bot className="h-4 w-4" />}
            label="Agents available"
            value={`${data.agents_available} / ${data.agents_total}`}
            tone={data.agents_available === data.agents_total ? "success" : "warning"}
          />
          <StatCard
            icon={<DollarSign className="h-4 w-4" />}
            label="Spend yesterday"
            value={formatCurrency(data.spend.yesterday_usd)}
            sub={`MTD ${formatCurrency(data.spend.mtd_usd)} of ${formatCurrency(data.spend.monthly_budget_usd)} (${formatPercent(spendPct)})`}
          />
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm">
                <Server className="h-4 w-4" /> Model routing
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <RoutingRow label="Anthropic API" status={data.routing.anthropic} />
              <RoutingRow label="On-prem inference" status={data.routing.on_prem} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Queue depth by lane</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {(["tier-0-mandatory", "tier-1-spotcheck", "tier-2-auto"] as const).map((lane) => {
                const n = data.queue_depth[lane];
                const max = Math.max(1, totalQueue);
                return (
                  <div key={lane} className="space-y-1">
                    <div className="flex items-center justify-between text-xs">
                      <span>{LANE_META[lane].short}</span>
                      <span className="font-mono">{n}</span>
                    </div>
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                      <div className={`h-full ${LANE_META[lane].color}`} style={{ width: `${(n / max) * 100}%` }} />
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        </div>

        <HashChainVerifier initial={data.audit_chain} />
      </div>
    </AppShell>
  );
}

function RoutingRow({ label, status }: { label: string; status: "ok" | "degraded" | "down" | "n/a" }) {
  return (
    <div className="flex items-center justify-between">
      <span>{label}</span>
      <Badge variant={STATUS_TONE[status]}>{status}</Badge>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  sub,
  tone = "default",
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  tone?: "default" | "success" | "warning" | "destructive";
}) {
  const toneClass =
    tone === "success"
      ? "text-success"
      : tone === "warning"
        ? "text-warning"
        : tone === "destructive"
          ? "text-destructive"
          : "";
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
          {icon}
          {label}
        </div>
        <div className={`mt-1 text-2xl font-semibold tabular-nums ${toneClass}`}>{value}</div>
        {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
      </CardContent>
    </Card>
  );
}
