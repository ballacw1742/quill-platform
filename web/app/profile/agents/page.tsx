"use client";

import * as React from "react";
import { ArrowDown, ArrowUp, Bot, ChevronRight } from "lucide-react";
import { MobileShell, TopBar, BackButton } from "@/components/layout/MobileShell";
import { GroupedList, ListGroup } from "@/components/ui/grouped-list";
import { ListRow } from "@/components/ui/list-row";
import { EmptyState } from "@/components/ui/empty-state";
import {
  BottomSheet,
  BottomSheetActionBar,
  BottomSheetBody,
  BottomSheetTopBar,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { BiometricPrompt } from "@/components/ui/biometric-prompt";
import { useAgents, useSetTrustTier } from "@/lib/api";
import type { Agent } from "@/lib/schemas";
import { formatCurrency, formatPercent } from "@/lib/utils";
import { toast } from "sonner";

/**
 * /profile/agents — replaces /agents.
 *
 * iOS Settings-style grouped list per agent showing:
 *   name · version · trust tier · default lane · last active.
 *
 * Tap a row → BottomSheet with full data + promote/demote actions
 * gated behind the BiometricPrompt overlay.
 *
 * The trust-tier promote/demote contract (useSetTrustTier hook) is
 * unchanged from the legacy /agents page — we just re-render it with
 * iOS primitives.
 */

const TIERS: Agent["trust_tier"][] = ["tier-0", "tier-1", "tier-2"];
const TIER_TONE: Record<Agent["trust_tier"], "danger" | "warning" | "success"> = {
  "tier-0": "danger",
  "tier-1": "warning",
  "tier-2": "success",
};

export default function ProfileAgentsPage() {
  const { data, isLoading } = useAgents();
  const agents = (data ?? []) as Agent[];
  const setTier = useSetTrustTier();

  const [openAgent, setOpenAgent] = React.useState<Agent | null>(null);
  const [pendingTier, setPendingTier] = React.useState<{
    agent: Agent;
    next: Agent["trust_tier"];
  } | null>(null);
  const [biometricOpen, setBiometricOpen] = React.useState(false);

  const startMove = (agent: Agent, next: Agent["trust_tier"]) => {
    setPendingTier({ agent, next });
    setBiometricOpen(true);
  };

  return (
    <MobileShell>
      <TopBar
        title="Agents"
        left={<BackButton href="/profile" label="Profile" />}
      />

      <GroupedList>
        {isLoading ? (
          <ListGroup>
            <div className="px-4 py-6 text-center text-callout text-label-secondary">
              Loading…
            </div>
          </ListGroup>
        ) : agents.length === 0 ? (
          <EmptyState
            icon={<Bot />}
            title="No agents registered"
            subtitle="Agents appear here once the runtime registers them."
          />
        ) : (
          <ListGroup
            title={`${agents.length} agent${agents.length === 1 ? "" : "s"}`}
          >
            {agents.map((a, i) => (
              <ListRow
                key={a.agent_id}
                icon={<Bot className="h-4 w-4" />}
                iconTone={TIER_TONE[a.trust_tier as Agent["trust_tier"]] ?? "neutral"}
                title={a.agent_id}
                subtitle={`v${a.version} · ${a.trust_tier}`}
                chip={`${formatPercent(a.error_rate ?? 0, 1)} err`}
                onClick={() => setOpenAgent(a)}
                hideDivider={i === agents.length - 1}
              />
            ))}
          </ListGroup>
        )}
      </GroupedList>

      {/* Agent detail sheet */}
      <BottomSheet
        open={!!openAgent}
        onOpenChange={(v) => !v && setOpenAgent(null)}
        ariaLabel="Agent detail"
        fullHeight
      >
        <BottomSheetTopBar
          title={openAgent?.agent_id ?? "Agent"}
          left={
            <button
              type="button"
              onClick={() => setOpenAgent(null)}
              className="text-body text-accent active:opacity-60 no-tap-highlight min-h-[44px] -ml-2 px-2"
            >
              Done
            </button>
          }
        />
        <BottomSheetBody>
          {openAgent && <AgentDetail agent={openAgent} />}
        </BottomSheetBody>
        {openAgent && (
          <BottomSheetActionBar>
            <Button
              variant="secondary"
              className="h-[50px] flex-1 rounded-lg text-headline"
              onClick={() => {
                const idx = TIERS.indexOf(openAgent.trust_tier as Agent["trust_tier"]);
                const demote = idx > 0 ? TIERS[idx - 1] : null;
                if (demote) startMove(openAgent, demote);
                setOpenAgent(null);
              }}
              disabled={
                TIERS.indexOf(openAgent.trust_tier as Agent["trust_tier"]) <= 0
              }
            >
              <ArrowDown className="h-4 w-4" /> Demote
            </Button>
            <Button
              className="h-[50px] flex-1 rounded-lg text-headline"
              onClick={() => {
                const idx = TIERS.indexOf(openAgent.trust_tier as Agent["trust_tier"]);
                const promote = idx < TIERS.length - 1 ? TIERS[idx + 1] : null;
                if (promote) startMove(openAgent, promote);
                setOpenAgent(null);
              }}
              disabled={
                TIERS.indexOf(openAgent.trust_tier as Agent["trust_tier"]) >=
                TIERS.length - 1
              }
            >
              <ArrowUp className="h-4 w-4" /> Promote
            </Button>
          </BottomSheetActionBar>
        )}
      </BottomSheet>

      <BiometricPrompt
        open={biometricOpen}
        onOpenChange={(v) => {
          setBiometricOpen(v);
          if (!v) setPendingTier(null);
        }}
        title={
          pendingTier
            ? `Move ${pendingTier.agent.agent_id} → ${pendingTier.next}`
            : "Confirm"
        }
        description="Trust tier changes are recorded in the audit log."
        // No actionIntent on this admin-side action — the existing hook
        // doesn't bind a passkey assertion to it. The prompt acts as a
        // soft confirmation gate.
        onConfirm={async () => {
          if (!pendingTier) return;
          try {
            await setTier.mutateAsync({
              agent_id: pendingTier.agent.agent_id,
              trust_tier: pendingTier.next,
            });
            toast.success(
              `${pendingTier.agent.agent_id} → ${pendingTier.next}`,
            );
          } catch (e) {
            toast.error(e instanceof Error ? e.message : "Failed");
          }
        }}
      />
    </MobileShell>
  );
}

function AgentDetail({ agent }: { agent: Agent }) {
  const spendPct =
    (agent.spend_mtd_usd ?? 0) /
    Math.max(1, agent.monthly_budget_usd ?? 0);

  return (
    <div className="space-y-5">
      <section className="rounded-xl bg-bg-elevated p-4 space-y-2">
        <div className="text-caption-1 uppercase tracking-wider text-label-secondary">
          Identity
        </div>
        <DetailRow k="Agent" v={agent.agent_id} mono />
        <DetailRow k="Version" v={`v${agent.version}`} mono />
        <DetailRow k="Trust tier" v={String(agent.trust_tier)} />
        <DetailRow
          k="Default lane"
          v={agent.default_lane != null ? String(agent.default_lane) : "—"}
        />
      </section>

      <section className="rounded-xl bg-bg-elevated p-4 space-y-3">
        <div className="text-caption-1 uppercase tracking-wider text-label-secondary">
          Spend (MTD)
        </div>
        <DetailRow
          k="Used"
          v={formatCurrency(agent.spend_mtd_usd ?? 0)}
        />
        <DetailRow
          k="Budget"
          v={formatCurrency(agent.monthly_budget_usd ?? 0)}
        />
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-bg-tertiary">
          <div
            className={
              spendPct < 0.7
                ? "h-full bg-success"
                : spendPct < 0.9
                  ? "h-full bg-warning"
                  : "h-full bg-danger"
            }
            style={{ width: `${Math.min(100, spendPct * 100)}%` }}
          />
        </div>
        <div className="text-footnote text-label-tertiary text-right">
          {formatPercent(spendPct)} of budget
        </div>
      </section>

      <section className="rounded-xl bg-bg-elevated p-4 space-y-2">
        <div className="text-caption-1 uppercase tracking-wider text-label-secondary">
          Quality
        </div>
        <DetailRow k="Error rate" v={formatPercent(agent.error_rate ?? 0, 2)} />
        <DetailRow
          k="No-edit rate"
          v={formatPercent(agent.approval_no_edit_rate ?? 0)}
        />
        <DetailRow
          k="Proposals (30d)"
          v={String(agent.total_proposals_30d ?? 0)}
        />
        <DetailRow
          k="Last active"
          v={
            agent.last_active_at
              ? new Date(agent.last_active_at).toLocaleString()
              : "—"
          }
        />
      </section>

      {agent.notes && (
        <section className="rounded-xl bg-bg-elevated p-4 space-y-1">
          <div className="text-caption-1 uppercase tracking-wider text-label-secondary">
            Notes
          </div>
          <div className="text-callout text-label-primary">{agent.notes}</div>
        </section>
      )}
    </div>
  );
}

function DetailRow({
  k,
  v,
  mono = false,
}: {
  k: string;
  v: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-callout">
      <dt className="text-label-secondary">{k}</dt>
      <dd
        className={
          mono
            ? "font-mono text-footnote text-label-primary"
            : "text-label-primary text-right truncate"
        }
      >
        {v}
      </dd>
    </div>
  );
}
