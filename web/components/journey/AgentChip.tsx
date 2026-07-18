"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { agentTrust, displayName, description as agentDescription } from "@/lib/agent-meta";

/**
 * AgentChip — compact identity chip for an agent, with a trust-tier dot.
 *   • Frontier (info)   — frontier model, may see sensitive data.
 *   • On-prem (success) — open-source model on-prem, non-sensitive only.
 * Tap to reveal capabilities, model, and data scope.
 *
 * Ported from the Lovable redesign; radix Popover swapped for a lightweight
 * self-contained toggle (prod has no ui/popover primitive).
 */
export function AgentChip({
  agentId,
  className,
}: {
  agentId: string;
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);
  const trust = agentTrust(agentId);
  const name = displayName(agentId);
  const desc = agentDescription(agentId);

  const isFrontier = trust.tier === "frontier";
  const dotClass = isFrontier ? "bg-info" : "bg-success";
  const tierLabel = isFrontier ? "Frontier" : "On-prem";

  React.useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  return (
    <div ref={ref} className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full border border-hairline",
          "bg-bg-elevated px-3 py-1.5 text-footnote no-tap-highlight shadow-card",
          "ease-ios transition active:scale-[0.98] duration-tap",
          className,
        )}
        aria-label={`${name}, ${tierLabel} agent`}
      >
        <span aria-hidden className={cn("h-1.5 w-1.5 shrink-0 rounded-full", dotClass)} />
        <span className="text-label-primary font-medium">{name}</span>
      </button>

      {open && (
        <div
          role="dialog"
          className="glass-strong absolute left-0 top-[calc(100%+6px)] z-40 w-72 rounded-2xl p-4"
        >
          <div className="flex items-center gap-2">
            <span aria-hidden className={cn("h-2 w-2 shrink-0 rounded-full", dotClass)} />
            <p className="text-headline text-label-primary">{name}</p>
          </div>
          {desc && <p className="mt-1 text-footnote text-label-secondary">{desc}</p>}
          <dl className="mt-3 space-y-1.5 text-caption-1">
            <div className="flex justify-between gap-4">
              <dt className="text-label-tertiary">Trust tier</dt>
              <dd className="text-label-primary font-medium">{tierLabel}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-label-tertiary">Model</dt>
              <dd className="text-label-primary font-medium">{trust.model}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-label-tertiary">Data scope</dt>
              <dd className="text-label-primary font-medium">
                {trust.dataScope === "sensitive" ? "Sensitive" : "Non-sensitive"}
              </dd>
            </div>
          </dl>
        </div>
      )}
    </div>
  );
}

/**
 * AgentTrustLegend — inline legend explaining the two trust dots.
 */
export function AgentTrustLegend({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-4 text-caption-1 text-label-secondary", className)}>
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-info" />
        Frontier
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-success" />
        On-prem
      </span>
    </div>
  );
}
