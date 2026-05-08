"use client";

import * as React from "react";
import { ArrowDown, ArrowUp, Bot } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { PasskeyChallengeModal } from "@/components/approval/PasskeyChallengeModal";
import { useAgents, useSetTrustTier } from "@/lib/api";
import type { Agent } from "@/lib/schemas";
import { formatCurrency, formatPercent } from "@/lib/utils";
import { toast } from "sonner";

const TIERS: Agent["trust_tier"][] = ["tier-0", "tier-1", "tier-2"];

const TIER_TONE: Record<Agent["trust_tier"], "destructive" | "warning" | "success"> = {
  "tier-0": "destructive",
  "tier-1": "warning",
  "tier-2": "success",
};

export default function AgentsPage() {
  const { data, isLoading } = useAgents();
  const agents = (data ?? []) as Agent[];
  const setTier = useSetTrustTier();
  const [pending, setPending] = React.useState<{ agent: Agent; next: Agent["trust_tier"] } | null>(
    null,
  );

  return (
    <AppShell>
      <div className="container mx-auto flex max-w-[1400px] flex-col gap-4 px-3 py-4 md:px-6">
        <div className="flex items-center gap-2">
          <Bot className="h-5 w-5" />
          <h1 className="text-lg font-semibold tracking-tight">Agent fleet</h1>
        </div>

        {isLoading ? (
          <Skeleton className="h-72" />
        ) : (
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Agent</TableHead>
                  <TableHead>Version</TableHead>
                  <TableHead>Trust tier</TableHead>
                  <TableHead className="text-right">MTD spend</TableHead>
                  <TableHead className="text-right">Error rate</TableHead>
                  <TableHead className="text-right">No-edit rate</TableHead>
                  <TableHead>Last active</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {agents.map((a) => {
                  const idx = TIERS.indexOf(a.trust_tier);
                  const promote = idx > 0 ? TIERS[idx - 1] : null; // toward tier-2 = more autonomy actually but spec uses "promote" colloquially. We map promote→less-restrictive.
                  // Re-map: tier-0 = strictest, tier-2 = most autonomy. Promote = move toward 2.
                  const promoteToward2 = idx < TIERS.length - 1 ? TIERS[idx + 1] : null;
                  const demoteToward0 = idx > 0 ? TIERS[idx - 1] : null;
                  const spendPct = a.spend_mtd_usd / a.monthly_budget_usd;
                  return (
                    <TableRow key={a.agent_id}>
                      <TableCell className="font-mono text-sm">{a.agent_id}</TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {a.version}
                      </TableCell>
                      <TableCell>
                        <Badge variant={TIER_TONE[a.trust_tier]}>{a.trust_tier}</Badge>
                      </TableCell>
                      <TableCell className="text-right text-xs">
                        <div className="font-medium">{formatCurrency(a.spend_mtd_usd)}</div>
                        <div className="text-muted-foreground">
                          of {formatCurrency(a.monthly_budget_usd)} ({formatPercent(spendPct)})
                        </div>
                        <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                          <div
                            className={
                              spendPct < 0.7
                                ? "h-full bg-success"
                                : spendPct < 0.9
                                  ? "h-full bg-warning"
                                  : "h-full bg-destructive"
                            }
                            style={{ width: `${Math.min(100, spendPct * 100)}%` }}
                          />
                        </div>
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs">
                        {formatPercent(a.error_rate, 2)}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs">
                        {formatPercent(a.approval_no_edit_rate)}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {a.last_active_at ? new Date(a.last_active_at).toLocaleString() : "—"}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="inline-flex gap-1">
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={!demoteToward0}
                            onClick={() =>
                              demoteToward0 && setPending({ agent: a, next: demoteToward0 })
                            }
                            title="Demote (more restrictive)"
                          >
                            <ArrowDown className="h-3.5 w-3.5" /> Demote
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={!promoteToward2}
                            onClick={() =>
                              promoteToward2 && setPending({ agent: a, next: promoteToward2 })
                            }
                            title="Promote (more autonomy)"
                          >
                            <ArrowUp className="h-3.5 w-3.5" /> Promote
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      <PasskeyChallengeModal
        open={!!pending}
        onOpenChange={(v) => !v && setPending(null)}
        title={pending ? `Move ${pending.agent.agent_id} → ${pending.next}` : "Confirm"}
        description="Trust tier changes are recorded in the audit log."
        onConfirm={async () => {
          if (!pending) return;
          await setTier.mutateAsync(
            { agent_id: pending.agent.agent_id, trust_tier: pending.next },
            { onError: (e) => toast.error(e.message || "Failed") },
          );
          toast.success(`${pending.agent.agent_id} → ${pending.next}`);
        }}
      />
    </AppShell>
  );
}
