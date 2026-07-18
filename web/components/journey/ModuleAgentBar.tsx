"use client";

import * as React from "react";
import { AgentChip, AgentTrustLegend } from "./AgentChip";

/**
 * ModuleAgentBar — shows which agents power a given module, using the same
 * trust-tier chips as the journey. Rendered near the top of each module page
 * so agent provenance is legible everywhere.
 *
 * Ported from the Lovable redesign (components/quill/journey/ModuleAgentBar).
 */
const MODULE_AGENTS: Record<string, string[]> = {
  sites: ["site-researcher", "site-evaluator", "site-scorer", "site-status"],
  estimates: ["cost-estimator", "coordinator"],
  contracts: ["contract-reviewer", "coordinator"],
  projects: ["schedule-builder", "rfi-manager", "change-order", "progress-tracker"],
  operations: ["owner-reporting", "safety-aggregator", "coordinator"],
  compliance: ["coordinator"],
  "supply-chain": ["procurement-watch"],
  customers: ["owner-reporting", "comms-drafter"],
};

export function ModuleAgentBar({ moduleKey }: { moduleKey: string }) {
  const agents = MODULE_AGENTS[moduleKey];
  if (!agents || agents.length === 0) return null;
  return (
    <div className="mx-auto w-full max-w-[708px] px-4 pt-4 md:max-w-4xl md:px-8">
      <div className="flex items-center justify-between gap-3">
        <p className="text-caption-1 uppercase tracking-wide text-label-tertiary">
          Agents on this module
        </p>
        <AgentTrustLegend />
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {agents.map((a) => (
          <AgentChip key={a} agentId={a} />
        ))}
      </div>
    </div>
  );
}
