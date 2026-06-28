"use client";

/**
 * AgentSelector — dropdown that lets users pick which Quill agent handles
 * their request, overriding auto-classification.
 *
 * Rendered above the chat thread on the Requests page.
 * Closes on outside click or ESC.
 */

import * as React from "react";
import { ChevronDown, Check } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Agent definitions
// ---------------------------------------------------------------------------

export interface AgentDef {
  id: string;
  emoji: string;
  label: string;
  description: string;
  /** Maps to the intent field on POST /v1/requests */
  intent: string;
  examples: string[];
}

export const AGENTS: AgentDef[] = [
  {
    id: "coordinator",
    emoji: "🤖",
    label: "Coordinator",
    description: "Auto-routes your request to the right agent",
    intent: "general",
    examples: [
      "Estimate cost for this concrete scope",
      "Build a schedule for a 50K SF office fit-out",
      "Review this subcontract for red flags",
      "Draft an RFI about drawing conflict on grid B-4",
      "Process this change order from the MEP contractor",
      "Generate this week's owner report",
    ],
  },
  {
    id: "cost-estimator",
    emoji: "💰",
    label: "Cost Estimator",
    description: "Upload drawings or scope documents to generate a detailed cost estimate",
    intent: "estimate",
    examples: [
      "Estimate cost for this concrete scope",
      "Price this electrical scope from the drawings",
      "What's the unit cost for structural steel per SF?",
      "Generate a CSI-formatted estimate from this scope narrative",
    ],
  },
  {
    id: "schedule-builder",
    emoji: "📅",
    label: "Schedule Builder",
    description: "Submit milestones or scope to generate a project schedule with critical path analysis",
    intent: "schedule",
    examples: [
      "Build a schedule for a 50K SF office fit-out",
      "Identify the critical path in this activity list",
      "How long will the MEP rough-in take given these constraints?",
      "Generate a Gantt from this scope narrative",
    ],
  },
  {
    id: "rfi-manager",
    emoji: "📋",
    label: "RFI Manager",
    description: "Submit questions or clarifications; routes to the right party and drafts the response",
    intent: "rfi",
    examples: [
      "Draft an RFI about drawing conflict on grid B-4",
      "There's a spec conflict between Division 03 and the structural drawings",
      "Who should we direct this question about waterproofing to?",
      "Submit an RFI for missing door hardware schedule",
    ],
  },
  {
    id: "contract-reviewer",
    emoji: "📄",
    label: "Contract Reviewer",
    description: "Upload contracts or agreements for clause analysis, red flags, and summary",
    intent: "contract",
    examples: [
      "Review this subcontract for red flags",
      "Summarize the liability clauses in this agreement",
      "Flag any missing insurance requirements",
      "What are the payment terms in this subcontract?",
    ],
  },
  {
    id: "change-order",
    emoji: "🔄",
    label: "Change Order Processor",
    description: "Submit change order requests for cost and schedule impact analysis",
    intent: "general",
    examples: [
      "Process this change order from the MEP contractor",
      "Analyze the cost impact of this scope addition",
      "What's the schedule impact of this change order?",
      "Draft a change order for the added electrical panels",
    ],
  },
  {
    id: "progress-tracker",
    emoji: "📊",
    label: "Progress Tracker",
    description: "Upload field reports to generate progress summaries",
    intent: "general",
    examples: [
      "Summarize this week's field reports",
      "What percent complete is the structural package?",
      "Identify behind-schedule activities from these reports",
      "Generate a progress summary for the owner",
    ],
  },
  {
    id: "owner-reporting",
    emoji: "👤",
    label: "Owner Reporting",
    description: "Generate owner-facing status reports from project data",
    intent: "general",
    examples: [
      "Generate this week's owner report",
      "Create an executive summary of project status",
      "Draft the monthly owner report for July",
      "Summarize budget, schedule, and risks for the owner",
    ],
  },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface AgentSelectorProps {
  selected: AgentDef;
  onSelect: (agent: AgentDef) => void;
}

export function AgentSelector({ selected, onSelect }: AgentSelectorProps) {
  const [open, setOpen] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);

  // Close on outside click
  React.useEffect(() => {
    if (!open) return;
    function handleOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function handleEsc(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("keydown", handleEsc);
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("keydown", handleEsc);
    };
  }, [open]);

  function handleSelect(agent: AgentDef) {
    onSelect(agent);
    setOpen(false);
  }

  return (
    <div ref={containerRef} className="relative px-4 py-2 border-b border-separator/30">
      {/* Trigger */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex w-full items-center gap-3 rounded-xl border border-separator/60 bg-bg-elevated px-3 py-2.5",
          "text-left transition-colors active:bg-bg-secondary",
          open && "border-accent/40 ring-1 ring-accent/20",
        )}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Select agent"
      >
        <span className="text-xl leading-none shrink-0">{selected.emoji}</span>
        <div className="flex-1 min-w-0">
          <p className="text-callout font-medium text-label-primary leading-tight">
            {selected.label}
          </p>
          <p className="text-caption-1 text-label-secondary truncate leading-snug mt-0.5">
            {selected.description}
          </p>
        </div>
        <ChevronDown
          className={cn(
            "h-4 w-4 text-label-tertiary shrink-0 transition-transform duration-200",
            open && "rotate-180",
          )}
          aria-hidden
        />
      </button>

      {/* Dropdown panel */}
      {open && (
        <div
          role="listbox"
          aria-label="Agent options"
          className={cn(
            "absolute left-4 right-4 top-full mt-1 z-50",
            "rounded-2xl border border-separator/60 bg-chrome shadow-lg shadow-black/20",
            "overflow-hidden",
          )}
        >
          <div className="max-h-[60vh] overflow-y-auto py-1">
            {AGENTS.map((agent) => {
              const isSelected = agent.id === selected.id;
              return (
                <button
                  key={agent.id}
                  role="option"
                  aria-selected={isSelected}
                  type="button"
                  onClick={() => handleSelect(agent)}
                  className={cn(
                    "flex w-full items-center gap-3 px-4 py-3 text-left",
                    "transition-colors hover:bg-bg-elevated active:bg-bg-secondary",
                    isSelected && "bg-accent/5",
                  )}
                >
                  <span className="text-xl leading-none shrink-0 w-7 text-center">
                    {agent.emoji}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p
                      className={cn(
                        "text-callout font-medium leading-tight",
                        isSelected ? "text-accent" : "text-label-primary",
                      )}
                    >
                      {agent.label}
                    </p>
                    <p className="text-caption-1 text-label-secondary leading-snug mt-0.5">
                      {agent.description}
                    </p>
                  </div>
                  {isSelected && (
                    <Check className="h-4 w-4 text-accent shrink-0" aria-hidden />
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
