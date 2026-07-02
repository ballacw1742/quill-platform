"use client";

/**
 * /customers — Customer Success module (Sprint 2A)
 *
 * Lists customer accounts with health scores, ticket counts, and portfolio summary.
 * Design: dark Quill theme, iOS-style cards, accent blue #0A84FF.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { Users, AlertTriangle, ChevronRight, Ticket } from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { ErrorBanner } from "@/components/ui/error-banner";
import { useCustomers, useCustomerSummary } from "@/lib/api";
import type { CustomerDetail, CustomerSummary, CustomerListPage } from "@/lib/schemas";

// ── Helpers ───────────────────────────────────────────────────────────────────

function healthColor(score: number | null | undefined): string {
  if (score == null) return "text-label-secondary";
  if (score >= 80) return "text-green-400";
  if (score >= 60) return "text-yellow-400";
  return "text-red-400";
}

function healthBarColor(score: number | null | undefined): string {
  if (score == null) return "bg-zinc-600";
  if (score >= 80) return "bg-green-400";
  if (score >= 60) return "bg-yellow-400";
  return "bg-red-400";
}

function ticketBadgeColor(count: number, hasCritical: boolean): string {
  if (count === 0) return "text-label-tertiary bg-bg-elevated";
  if (hasCritical) return "text-red-400 bg-red-400/10";
  return "text-yellow-400 bg-yellow-400/10";
}

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
    <div className="flex-1 min-w-0 rounded-2xl bg-chrome/80 border border-separator/40 p-3 flex flex-col gap-0.5">
      <p className="text-caption-2 text-label-secondary truncate">{label}</p>
      <p className={cn("text-title-3 font-bold", colorClass ?? "text-label-primary")}>{value}</p>
      {subtext && <p className="text-caption-2 text-label-tertiary truncate">{subtext}</p>}
    </div>
  );
}

// ── Customer Card ─────────────────────────────────────────────────────────────

function CustomerCard({
  customer,
  onClick,
}: {
  customer: CustomerDetail;
  onClick: () => void;
}) {
  const score = customer.health?.total ?? null;
  const hasCritical =
    (customer.health?.open_p1 ?? 0) > 0 || (customer.health?.open_p2 ?? 0) > 0;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full text-left rounded-2xl p-4 mb-3",
        "bg-chrome/80 border border-separator/40",
        "backdrop-blur-sm transition-all active:scale-[0.98] hover:border-separator/80",
        "shadow-sm shadow-black/10",
      )}
    >
      {/* Account name row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <p className="text-body font-semibold text-label-primary truncate">{customer.name}</p>
          {customer.industry && (
            <p className="text-caption-1 text-label-secondary truncate mt-0.5">{customer.industry}</p>
          )}
          {customer.primary_contact_name && (
            <p className="text-caption-2 text-label-tertiary truncate">{customer.primary_contact_name}</p>
          )}
        </div>
        <ChevronRight className="w-4 h-4 text-label-quaternary flex-shrink-0 mt-1" />
      </div>

      {/* Health score bar */}
      <div className="mt-3">
        <div className="flex items-center justify-between mb-1">
          <span className="text-caption-2 text-label-tertiary">Health</span>
          <span className={cn("text-caption-1 font-bold", healthColor(score))}>
            {score != null ? `${score}` : "—"}
          </span>
        </div>
        <div className="h-1.5 rounded-full bg-separator/30 overflow-hidden">
          <div
            className={cn("h-full rounded-full transition-all", healthBarColor(score))}
            style={{ width: `${score ?? 0}%` }}
          />
        </div>
      </div>

      {/* Badges row */}
      <div className="flex items-center gap-2 mt-3">
        {/* Ticket count badge */}
        <span
          className={cn(
            "flex items-center gap-1 text-caption-2 font-semibold rounded-full px-2 py-0.5",
            ticketBadgeColor(customer.open_ticket_count, hasCritical),
          )}
        >
          <Ticket className="w-3 h-3" />
          {customer.open_ticket_count} open
        </span>

        {/* Campus linked */}
        {customer.won_deal?.campus_id && (
          <span className="text-caption-2 text-accent bg-accent/10 rounded-full px-2 py-0.5 truncate max-w-[120px]">
            Campus linked
          </span>
        )}
      </div>
    </button>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function CustomersPage() {
  const router = useRouter();
  const { data: summaryRaw, isLoading: summaryLoading } = useCustomerSummary();
  const summary = summaryRaw as CustomerSummary | undefined;
  const { data: customersRaw, isLoading, error } = useCustomers();
  const customers = customersRaw as CustomerListPage | undefined;

  const avgHealthScore = summary?.avg_health_score;
  const avgHealthStr =
    avgHealthScore != null ? `${avgHealthScore.toFixed(0)}` : "—";
  const avgHealthColorClass = healthColor(avgHealthScore);

  return (
    <MobileShell>
      <TopBar
        title="Customers"
        left={<Users className="w-5 h-5 text-accent" />}
      />

      <div className="px-4 pb-safe-bottom overflow-y-auto">
        {/* Summary cards */}
        {!summaryLoading && summary && (
          <div className="flex gap-2 mt-4 mb-5">
            <SummaryCard
              label="Customers"
              value={summary.total_customers}
              colorClass="text-label-primary"
            />
            <SummaryCard
              label="Open Tickets"
              value={summary.open_tickets}
              colorClass={
                summary.has_critical_tickets
                  ? "text-red-400"
                  : summary.open_tickets > 0
                    ? "text-yellow-400"
                    : "text-label-primary"
              }
              subtext={summary.has_critical_tickets ? "P1/P2 open" : undefined}
            />
          </div>
        )}
        {!summaryLoading && summary && (
          <div className="flex gap-2 mb-6">
            <SummaryCard
              label="Avg Health"
              value={avgHealthStr}
              colorClass={avgHealthColorClass}
            />
            <SummaryCard
              label="At-Risk"
              value={summary.at_risk_count}
              colorClass={summary.at_risk_count > 0 ? "text-red-400" : "text-label-primary"}
              subtext="health < 60"
            />
          </div>
        )}

        {/* Error */}
        {error && <ErrorBanner message={error.message} />}

        {/* Loading skeleton */}
        {isLoading && (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-28 rounded-2xl bg-chrome/60 border border-separator/30 animate-pulse"
              />
            ))}
          </div>
        )}

        {/* Empty state */}
        {!isLoading && !error && ((customers?.items as CustomerDetail[] | undefined)?.length ?? 0) === 0 && (
          <div className="flex flex-col items-center justify-center py-16 gap-3">
            <AlertTriangle className="w-10 h-10 text-label-quaternary" />
            <p className="text-body text-label-secondary text-center max-w-xs">
              No customers yet. When a deal is marked Won in Pipeline, promote the
              account here.
            </p>
          </div>
        )}

        {/* Customer list */}
        {!isLoading && customers && (customers.items as CustomerDetail[]).length > 0 && (
          <div>
            {(customers.items as CustomerDetail[]).map((customer) => (
              <CustomerCard
                key={customer.id}
                customer={customer}
                onClick={() => router.push(`/customers/${customer.id}`)}
              />
            ))}
          </div>
        )}
      </div>
    </MobileShell>
  );
}
