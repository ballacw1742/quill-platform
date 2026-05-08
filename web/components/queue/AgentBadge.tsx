"use client";

import * as React from "react";
import {
  Bot,
  ClipboardList,
  FileText,
  Layers,
  ShieldAlert,
  Truck,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Compact 28 × 28 agent badge — matches MOBILE_UX_SPEC §1 row layout.
 *
 * The current API exposes free-form agent_id strings; map known prefixes to
 * an icon, and fall back to the agent's first two initials. Tone is mapped
 * to the agent's typical lane (rfi-* / safety-* are usually mandatory; etc.).
 */

const AGENT_ICON: Record<string, LucideIcon> = {
  "rfi-": FileText,
  "safety-": ShieldAlert,
  "procurement-": Truck,
  "schedule-": ClipboardList,
  "submittal-": Layers,
};

function pickIcon(agentId: string): LucideIcon {
  for (const prefix of Object.keys(AGENT_ICON)) {
    if (agentId.startsWith(prefix)) return AGENT_ICON[prefix];
  }
  return Bot;
}

function pickInitials(agentId: string): string {
  const parts = agentId.replace(/[^a-z0-9-]/gi, "").split("-").filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return "AG";
}

const TONES = [
  "bg-accent/10 text-accent",
  "bg-info/10 text-info",
  "bg-success/10 text-success",
  "bg-warning/10 text-warning",
  "bg-danger/10 text-danger",
];

function pickTone(agentId: string): string {
  // Stable hash so each agent maps to a consistent tone (visual recognition).
  let hash = 0;
  for (const ch of agentId) hash = (hash * 31 + ch.charCodeAt(0)) | 0;
  return TONES[Math.abs(hash) % TONES.length];
}

export function AgentBadge({
  agentId,
  className,
}: {
  agentId: string;
  className?: string;
}) {
  const Icon = pickIcon(agentId);
  const tone = pickTone(agentId);
  return (
    <span
      className={cn(
        "flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
        tone,
        className,
      )}
      aria-label={`agent ${agentId}`}
      title={agentId}
    >
      <Icon className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
    </span>
  );
}

// Re-export utility so callers can render an in-line label too.
export const agentInitials = pickInitials;
