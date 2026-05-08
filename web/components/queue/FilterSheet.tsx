"use client";

import * as React from "react";
import {
  BottomSheet,
  BottomSheetBody,
  BottomSheetTopBar,
  BottomSheetActionBar,
} from "@/components/ui/sheet";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { displayName, displayWorkflow } from "@/lib/agent-meta";

/**
 * Bottom-sheet filter controls for /queue, per MOBILE_UX_SPEC §"Filter sheet".
 *
 * Single source of truth for filter values; the queue page owns state and
 * passes value+onChange. "Reset" returns all filters to defaults; "Apply"
 * just closes (state is already lifted, no buffered apply step needed for
 * a client-only filter).
 */

export type QueueFilterValue = {
  agent: string; // "all" or specific agent_id
  workflow: string;
  age: "any" | "1h" | "24h" | "stale";
};

export const DEFAULT_FILTERS: QueueFilterValue = {
  agent: "all",
  workflow: "all",
  age: "any",
};

export function FilterSheet({
  open,
  onOpenChange,
  value,
  onChange,
  agents,
  workflows,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  value: QueueFilterValue;
  onChange: (next: QueueFilterValue) => void;
  agents: string[];
  workflows: string[];
}) {
  const set = <K extends keyof QueueFilterValue>(
    k: K,
    v: QueueFilterValue[K],
  ) => onChange({ ...value, [k]: v });

  return (
    <BottomSheet
      open={open}
      onOpenChange={onOpenChange}
      ariaLabel="Filter queue"
    >
      <BottomSheetTopBar
        title="Filters"
        right={
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="text-body text-accent active:opacity-60 no-tap-highlight min-h-[44px] -mr-2 px-2"
          >
            Done
          </button>
        }
      />
      <BottomSheetBody>
        <div className="flex flex-col gap-6 pt-2">
          <section className="space-y-2">
            <SectionHeader>Age</SectionHeader>
            <SegmentedControl
              value={value.age}
              onChange={(v) => set("age", v)}
              options={[
                { value: "any", label: "Any" },
                { value: "1h", label: "< 1h" },
                { value: "24h", label: "< 24h" },
                { value: "stale", label: "> 24h" },
              ]}
              ariaLabel="Age filter"
            />
          </section>

          <section className="space-y-2">
            <SectionHeader>Helper</SectionHeader>
            <ChipGroup
              value={value.agent}
              onChange={(v) => set("agent", v)}
              options={[
                { value: "all", label: "All" },
                ...agents.map((a) => ({ value: a, label: displayName(a) })),
              ]}
            />
          </section>

          <section className="space-y-2">
            <SectionHeader>Action type</SectionHeader>
            <ChipGroup
              value={value.workflow}
              onChange={(v) => set("workflow", v)}
              options={[
                { value: "all", label: "All" },
                ...workflows.map((w) => ({
                  value: w,
                  label: displayWorkflow(w),
                })),
              ]}
            />
          </section>
        </div>
      </BottomSheetBody>
      <BottomSheetActionBar>
        <Button
          variant="ghost"
          className="h-[50px] flex-1 rounded-lg text-headline"
          onClick={() => onChange(DEFAULT_FILTERS)}
        >
          Reset
        </Button>
        <Button
          className="h-[50px] flex-1 rounded-lg text-headline"
          onClick={() => onOpenChange(false)}
        >
          Apply
        </Button>
      </BottomSheetActionBar>
    </BottomSheet>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-caption-1 uppercase tracking-wider text-label-secondary">
      {children}
    </h3>
  );
}

function ChipGroup({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            aria-pressed={active}
            className={cn(
              "min-h-[44px] rounded-full border px-3 text-callout no-tap-highlight transition-colors duration-state",
              active
                ? "border-transparent bg-accent text-white"
                : "border-separator-opaque bg-bg-tertiary text-label-primary active:bg-bg-elevated",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
