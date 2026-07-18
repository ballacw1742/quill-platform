"use client";

import * as React from "react";
import { Bot, ToggleLeft, ToggleRight } from "lucide-react";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { SkelList } from "@/components/ui/skeletons";
import { toast } from "sonner";
import { useAgents, useToggleAgent } from "@/lib/api";
import { useSession } from "@/lib/api";
import type { Agent } from "@/lib/schemas";
import type { Session } from "@/lib/schemas";
import { cn } from "@/lib/utils";

/**
 * /agents — Agent Registry (Sprint DC.4)
 *
 * Card grid showing all 9 registered ADK agents with:
 * - Agent name, framework badge, role summary
 * - Description
 * - Handled intents as pills
 * - Usage stats (total requests, success rate, last invoked)
 * - Enable/disable toggle (owner/partner only)
 */

function parseIntents(raw: string | null | undefined): string[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function formatSuccessRate(total: number, success: number): string {
  if (total === 0) return "—";
  return `${Math.round((success / total) * 100)}%`;
}

function formatLastInvoked(iso: string | null | undefined): string {
  if (!iso) return "Never";
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    return d.toLocaleDateString();
  } catch {
    return "—";
  }
}

const FRAMEWORK_BADGE: Record<string, { label: string; className: string }> = {
  // Semantic tokens only — no Tailwind color-name classes (PALETTE RULE).
  adk:      { label: "ADK",      className: "bg-info/15 text-info" },
  datasite: { label: "DataSite", className: "bg-accent-tint text-accent" },
  internal: { label: "Internal", className: "bg-fill-quaternary text-label-secondary" },
};

function AgentCard({
  agent,
  canToggle,
  onToggle,
  toggling,
}: {
  agent: Agent;
  canToggle: boolean;
  onToggle: (id: string) => void;
  toggling: boolean;
}) {
  const intents = parseIntents(agent.handled_intents);
  const badge = FRAMEWORK_BADGE[agent.framework ?? "adk"] ?? FRAMEWORK_BADGE.adk;
  const successRate = formatSuccessRate(agent.requests_total ?? 0, agent.requests_success ?? 0);
  const lastInvoked = formatLastInvoked(agent.last_invoked_at);

  return (
    <div
      className={cn(
        "rounded-xl bg-bg-elevated border border-separator/30 p-4 flex flex-col gap-3 transition-opacity",
        !agent.enabled && "opacity-60",
      )}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent/10">
            <Bot className="h-4 w-4 text-accent" />
          </div>
          <div className="min-w-0">
            <div className="text-headline text-label-primary break-words">
              {agent.display_name || agent.agent_id}
            </div>
            {agent.role_summary && (
              <div className="text-footnote text-label-secondary break-words">
                {agent.role_summary}
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className={cn("text-caption-1 font-medium px-1.5 py-0.5 rounded", badge.className)}>
            {badge.label}
          </span>
          {canToggle && (
            <button
              type="button"
              onClick={() => onToggle(agent.agent_id)}
              disabled={toggling}
              className="min-h-[32px] min-w-[32px] flex items-center justify-center rounded-lg active:opacity-60 disabled:opacity-40 no-tap-highlight"
              aria-label={agent.enabled ? "Disable agent" : "Enable agent"}
            >
              {agent.enabled ? (
                <ToggleRight className="h-5 w-5 text-success" />
              ) : (
                <ToggleLeft className="h-5 w-5 text-label-tertiary" />
              )}
            </button>
          )}
        </div>
      </div>

      {/* Description */}
      {agent.description && (
        <p className="text-callout text-label-secondary break-words">
          {agent.description}
        </p>
      )}

      {/* Intent pills */}
      {intents.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {intents.map((intent) => (
            <span
              key={intent}
              className="text-caption-1 px-2 py-0.5 rounded-full bg-separator/30 text-label-secondary"
            >
              {intent.replace(/_/g, " ")}
            </span>
          ))}
        </div>
      )}

      {/* Stats */}
      <div className="flex items-center gap-4 pt-1 border-t border-separator/20">
        <StatPill label="Requests" value={String(agent.requests_total ?? 0)} />
        <StatPill label="Success" value={successRate} />
        <StatPill label="Last used" value={lastInvoked} />
        {!agent.enabled && (
          <span className="ml-auto text-caption-1 text-label-tertiary italic">disabled</span>
        )}
      </div>
    </div>
  );
}

function StatPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col items-start gap-0.5">
      <span className="text-caption-2 text-label-tertiary uppercase tracking-wide">{label}</span>
      <span className="text-callout font-medium text-label-primary">{value}</span>
    </div>
  );
}

export default function AgentsPage() {
  const { data: agentsRaw, isLoading, error, refetch } = useAgents();
  const { data: rawSession } = useSession();
  const session = rawSession as Session | null | undefined;
  const toggle = useToggleAgent();

  // The new /v1/agents returns {items, total}; old /v1/agents returns array.
  // useAgents returns Agent[] (array). Handle both shapes defensively.
  const agents = React.useMemo(() => {
    if (!agentsRaw) return [];
    if (Array.isArray(agentsRaw)) return agentsRaw as Agent[];
    const envelope = agentsRaw as { items?: Agent[] };
    return envelope.items ?? [];
  }, [agentsRaw]);

  const canToggle = session?.role === "owner" || session?.role === "partner";

  const handleToggle = async (agent_id: string) => {
    try {
      await toggle.mutateAsync({ agent_id });
      const agent = agents.find((a) => a.agent_id === agent_id);
      const wasEnabled = agent?.enabled ?? true;
      toast.success(`${agent?.display_name || agent_id} ${wasEnabled ? "disabled" : "enabled"}`);
    } catch (e) {
      toast.error("Couldn't toggle agent. Try again.");
    }
  };

  return (
    <MobileShell>
      <TopBar title="Agent Registry" />

      <div className="px-4 py-4">
        {error && !isLoading && (
          <ErrorBanner
            message="Couldn't load agents. Try again."
            onRetry={() => refetch()}
          />
        )}

        {isLoading ? (
          <SkelList
            ariaLabel="Loading agents"
            count={6}
            className="rounded-xl overflow-hidden"
          />
        ) : agents.length === 0 ? (
          <EmptyState
            icon={<Bot />}
            title="No agents registered."
            subtitle="Agents appear here once they're registered and seeded on startup."
          />
        ) : (
          <div className="flex flex-col gap-3">
            <div className="text-footnote text-label-secondary mb-1">
              {agents.length} agent{agents.length !== 1 ? "s" : ""} registered
            </div>
            {agents.map((agent) => (
              <AgentCard
                key={agent.agent_id}
                agent={agent}
                canToggle={canToggle}
                onToggle={handleToggle}
                toggling={toggle.isPending}
              />
            ))}
          </div>
        )}
      </div>
    </MobileShell>
  );
}
