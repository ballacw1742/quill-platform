"use client";

/**
 * /customers — Customer Success module
 *
 * Ported visual layer from Lovable: quill-platform-builder/src/routes/customers.tsx
 * Data wiring kept from prod; routing via next/navigation.
 *
 * Key token mappings (LOVABLE_PORT_CONTRACT § Known token equivalences):
 *   bg-bg-elevated shadow-card  — used for summary + skeleton cards
 *   text-danger / text-warning  — semantic color tokens (exist in prod)
 *   healthColor()               — imported from CustomerCard (text-success/warning/danger)
 *   No inline hex. No emojis.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { ErrorBanner } from "@/components/ui/error-banner";
import { CustomerCard, healthColor } from "@/components/customers/CustomerCard";
import { useCustomers, useCustomerSummary } from "@/lib/api";
import type { CustomerDetail, CustomerSummary, CustomerListPage } from "@/lib/schemas";

// ── Summary Card ──────────────────────────────────────────────────────────────

function SummaryCard({
  label,
  value,
  subtext,
  colorClass,
}: {
  label: string;
  value: string | number;
  subtext?: string;
  colorClass?: string;
}) {
  return (
    <div className="flex-1 min-w-0 rounded-2xl bg-bg-elevated shadow-card p-3 flex flex-col gap-0.5">
      <p className="text-caption-2 text-label-secondary truncate">{label}</p>
      <p className={cn("text-title-3", colorClass ?? "text-label-primary")}>{value}</p>
      {subtext && <p className="text-caption-2 text-label-tertiary truncate">{subtext}</p>}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function CustomersPage() {
  const router = useRouter();
  const { data: summaryRaw, isLoading: summaryLoading } = useCustomerSummary();
  const summary = summaryRaw as CustomerSummary | undefined;
  const { data: customersRaw, isLoading, error } = useCustomers();
  const customers = customersRaw as CustomerListPage | undefined;

  const avgScore = summary?.avg_health_score;
  const avgStr = avgScore != null ? `${avgScore.toFixed(0)}` : "—";

  return (
    <MobileShell>
      <TopBar
        title="Customers"
        left={<Users className="w-5 h-5 text-accent" />}
      />

      <div className="px-4 pb-safe-bottom overflow-y-auto">
        {!summaryLoading && summary && (
          <>
            <div className="flex gap-2 mt-4 mb-3">
              <SummaryCard
                label="Customers"
                value={summary.total_customers}
              />
              <SummaryCard
                label="Open Tickets"
                value={summary.open_tickets}
                colorClass={
                  summary.has_critical_tickets
                    ? "text-danger"
                    : summary.open_tickets > 0
                      ? "text-warning"
                      : "text-label-primary"
                }
                subtext={summary.has_critical_tickets ? "P1/P2 open" : undefined}
              />
            </div>
            <div className="flex gap-2 mb-6">
              <SummaryCard
                label="Avg Health"
                value={avgStr}
                colorClass={healthColor(avgScore)}
              />
              <SummaryCard
                label="At-Risk"
                value={summary.at_risk_count}
                colorClass={
                  summary.at_risk_count > 0
                    ? "text-danger"
                    : "text-label-primary"
                }
                subtext="health < 60"
              />
            </div>
          </>
        )}

        {/* Error */}
        {error && <ErrorBanner message={error.message} />}

        {/* Loading skeleton */}
        {isLoading && (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-28 rounded-2xl bg-bg-elevated shadow-card animate-pulse"
              />
            ))}
          </div>
        )}

        {/* Empty state */}
        {!isLoading && !error && ((customers?.items as CustomerDetail[] | undefined)?.length ?? 0) === 0 && (
          <div className="flex flex-col items-center justify-center py-16 gap-3">
            <AlertTriangle className="w-10 h-10 text-label-tertiary" />
            <p className="text-body text-label-secondary text-center max-w-xs">
              No customers yet. When a deal is marked Won in Pipeline, promote
              the account here.
            </p>
          </div>
        )}

        {/* Customer list */}
        {!isLoading && customers && (customers.items as CustomerDetail[]).length > 0 && (
          <div className="flex flex-col gap-3">
            {(customers.items as CustomerDetail[]).map((c) => (
              <CustomerCard
                key={c.id}
                customer={c}
                onClick={() => router.push(`/customers/${c.id}`)}
              />
            ))}
          </div>
        )}
      </div>
    </MobileShell>
  );
}
