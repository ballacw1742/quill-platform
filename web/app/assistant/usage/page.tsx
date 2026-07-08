"use client";

/**
 * /assistant/usage — Usage & budget meters (Phase B2 data, surfaced in
 * Phase E). agent-cloud/LIMITS.md §2.
 *
 * Read-only, simple, honest. Renders GET /v1/agent-cloud/usage:
 *   - tenant month-to-date spend vs. monthly budget + remaining + posture
 *   - per-agent meters (every defined agent, zero-usage included)
 *   - request counts + token totals
 *
 * tenant_id never appears here — the bridge injects it from the JWT
 * (workspace=personal|org). No mutations; this is a dashboard.
 */

import * as React from "react";

import { BackButton, MobileShell, TopBar } from "@/components/layout/MobileShell";
import { Badge } from "@/components/ui/badge";
import {
  budgetPostureLabel,
  fmtUsd,
  spendFraction,
  useAgentCloudUsage,
  type UsageAgent,
} from "@/lib/agent-cloud";

const AGENT_LABELS: Record<string, string> = {
  personal: "Personal",
  quill: "Quill",
};

function labelFor(agentId: string): string {
  return AGENT_LABELS[agentId] ?? agentId;
}

/** A spend/budget meter bar. Turns amber near cap, red when exhausted. */
export function MeterBar({
  spend,
  budget,
  exhausted,
}: {
  spend: number;
  budget: number;
  exhausted: boolean;
}) {
  const f = spendFraction(spend, budget);
  const pct = Math.round(f * 100);
  const color = exhausted || f >= 1 ? "bg-red-500" : f >= 0.9 ? "bg-amber-500" : "bg-accent";
  return (
    <div
      className="h-2 w-full overflow-hidden rounded-full bg-bg-elevated"
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label="Budget used"
    >
      <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function TokenLine({ input, output, requests }: { input: number; output: number; requests: number }) {
  return (
    <p className="mt-1 text-caption-1 text-label-secondary">
      {requests.toLocaleString()} requests · {input.toLocaleString()} in /{" "}
      {output.toLocaleString()} out tokens
    </p>
  );
}

function AgentMeter({ a }: { a: UsageAgent }) {
  return (
    <div className="rounded-xl border border-separator bg-chrome px-4 py-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-body font-medium text-label-primary">
          {labelFor(a.agent_id)}
        </span>
        <span className="text-footnote text-label-secondary">
          {fmtUsd(a.spend_usd)} / {fmtUsd(a.budget_monthly_usd)}
        </span>
      </div>
      <div className="mt-2">
        <MeterBar spend={a.spend_usd} budget={a.budget_monthly_usd} exhausted={a.exhausted} />
      </div>
      <div className="mt-1 flex items-center justify-between">
        <span className="text-caption-1 text-label-secondary">
          {fmtUsd(a.remaining_usd)} remaining
        </span>
        {a.exhausted && <Badge variant="warning">exhausted</Badge>}
      </div>
      <TokenLine input={a.input_tokens} output={a.output_tokens} requests={a.requests} />
    </div>
  );
}

export default function UsagePage() {
  const usage = useAgentCloudUsage();
  const data = usage.data;

  return (
    <MobileShell>
      <div className="mx-auto flex min-h-screen w-full max-w-2xl flex-col">
        <TopBar title="Usage & budget" left={<BackButton href="/assistant" label="Assistant" />} />

        <div className="flex-1 px-4 pb-16 pt-4">
          {usage.isLoading && (
            <p className="px-1 py-6 text-center text-footnote text-label-secondary">
              Loading usage…
            </p>
          )}

          {usage.isError && (
            <p className="px-1 py-6 text-center text-footnote text-label-secondary">
              Couldn&apos;t load usage. Pull to retry.
            </p>
          )}

          {data && (
            <>
              {/* Tenant summary */}
              <section className="rounded-2xl border border-separator bg-chrome px-4 py-4">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-caption-1 uppercase tracking-wide text-label-secondary">
                    This workspace · {data.month}
                  </span>
                  <Badge variant={data.tenant.budget_source === "override" ? "muted" : "muted"}>
                    {data.tenant.budget_source === "override" ? "custom cap" : "default cap"}
                  </Badge>
                </div>
                <div className="mt-2 flex items-baseline gap-2">
                  <span className="text-title-1 font-semibold text-label-primary">
                    {fmtUsd(data.tenant.spend_usd)}
                  </span>
                  <span className="text-body text-label-secondary">
                    of {fmtUsd(data.tenant.budget_monthly_usd)}
                  </span>
                </div>
                <div className="mt-3">
                  <MeterBar
                    spend={data.tenant.spend_usd}
                    budget={data.tenant.budget_monthly_usd}
                    exhausted={data.tenant.exhausted}
                  />
                </div>
                <p className="mt-2 text-footnote text-label-secondary">
                  {fmtUsd(data.tenant.remaining_usd)} remaining ·{" "}
                  {budgetPostureLabel(data.tenant)}
                </p>
                <TokenLine
                  input={data.tenant.input_tokens}
                  output={data.tenant.output_tokens}
                  requests={data.tenant.requests}
                />
              </section>

              {/* Per-agent meters */}
              <h2 className="mb-2 mt-6 px-1 text-footnote font-medium uppercase tracking-wide text-label-secondary">
                Per agent
              </h2>
              <div className="flex flex-col gap-2">
                {data.agents.map((a) => (
                  <AgentMeter key={a.agent_id} a={a} />
                ))}
                {data.agents.length === 0 && (
                  <p className="px-1 py-6 text-center text-footnote text-label-secondary">
                    No agents yet.
                  </p>
                )}
              </div>

              <p className="mt-6 px-1 text-caption-1 text-label-tertiary">
                Budgets are monthly (UTC calendar month) and reset on the 1st. When a
                cap is reached, turns are politely refused with no model call — never an
                error. Rate limits (per-minute) apply separately.
              </p>
            </>
          )}
        </div>
      </div>
    </MobileShell>
  );
}
