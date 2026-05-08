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
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { displayName } from "@/lib/agent-meta";
import {
  artifactTypeLabel,
  type DocumentFilterValue,
} from "@/lib/document-meta";

/**
 * DocumentsFilterSheet — Phase E commit 4.
 *
 * Multi-axis filter sheet behind the SlidersHorizontal button on /documents.
 * Per DESIGN_SYSTEM §"Sheets" + COPY_GUIDE voice.
 *
 * Filters:
 *   - artifact type (multi-select chips, distinct from the segmented
 *     control on the page; chosen for richer cross-cutting filtering)
 *   - agent (multi-select chips)
 *   - date range (segmented: Any / Today / This week / This month / Custom)
 *   - tags (free-text, comma-separated → trimmed list)
 *
 * Sheet uses a draft → Apply pattern (uncommitted changes don't apply
 * until the user taps "Apply"). "Reset" zeroes the draft.
 */

export type DocumentDateRange =
  | "any"
  | "today"
  | "week"
  | "month"
  | "custom";

export type DocumentsFilterValue = {
  artifactTypes: DocumentFilterValue[]; // empty = no artifact-type constraint
  agents: string[]; // empty = all agents
  dateRange: DocumentDateRange;
  customSince: string | null; // ISO date "YYYY-MM-DD" when dateRange = "custom"
  tagsRaw: string; // free-text comma-separated; resolved to list at apply time
};

export const DEFAULT_DOCS_FILTERS: DocumentsFilterValue = {
  artifactTypes: [],
  agents: [],
  dateRange: "any",
  customSince: null,
  tagsRaw: "",
};

export function isDefault(v: DocumentsFilterValue): boolean {
  return (
    v.artifactTypes.length === 0 &&
    v.agents.length === 0 &&
    v.dateRange === "any" &&
    !v.customSince &&
    v.tagsRaw.trim().length === 0
  );
}

/** Returns an active-filter count for the chip badge next to the icon. */
export function activeCount(v: DocumentsFilterValue): number {
  let n = 0;
  if (v.artifactTypes.length > 0) n++;
  if (v.agents.length > 0) n++;
  if (v.dateRange !== "any") n++;
  if (v.tagsRaw.trim().length > 0) n++;
  return n;
}

/** Parses the comma-separated raw tag input into a normalized list of tags. */
export function parseTagsRaw(raw: string): string[] {
  return raw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

const ARTIFACT_TYPE_OPTIONS: { value: DocumentFilterValue; label: string }[] = [
  { value: "status_update", label: artifactTypeLabel("status_update") },
  { value: "coordinator_artifact", label: artifactTypeLabel("coordinator_artifact") },
  { value: "pm_analysis", label: artifactTypeLabel("pm_analysis") },
  { value: "comms_draft", label: artifactTypeLabel("comms_draft") },
  { value: "knowledge_entry", label: artifactTypeLabel("knowledge_entry") },
];

export function DocumentsFilterSheet({
  open,
  onOpenChange,
  value,
  onChange,
  agents,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  value: DocumentsFilterValue;
  onChange: (next: DocumentsFilterValue) => void;
  /** List of agent_id values present in the current dataset. */
  agents: string[];
}) {
  // Draft state — uncommitted edits live here until Apply.
  const [draft, setDraft] = React.useState<DocumentsFilterValue>(value);

  // When the sheet opens, hydrate the draft from the current applied value.
  React.useEffect(() => {
    if (open) setDraft(value);
  }, [open, value]);

  const setDraftField = <K extends keyof DocumentsFilterValue>(
    k: K,
    v: DocumentsFilterValue[K],
  ) => setDraft((prev) => ({ ...prev, [k]: v }));

  const toggleArtifactType = (t: DocumentFilterValue) => {
    setDraftField(
      "artifactTypes",
      draft.artifactTypes.includes(t)
        ? draft.artifactTypes.filter((x) => x !== t)
        : [...draft.artifactTypes, t],
    );
  };

  const toggleAgent = (id: string) => {
    setDraftField(
      "agents",
      draft.agents.includes(id)
        ? draft.agents.filter((x) => x !== id)
        : [...draft.agents, id],
    );
  };

  const apply = () => {
    onChange(draft);
    onOpenChange(false);
  };

  const reset = () => {
    setDraft(DEFAULT_DOCS_FILTERS);
  };

  return (
    <BottomSheet
      open={open}
      onOpenChange={onOpenChange}
      ariaLabel="Filter documents"
      fullHeight
    >
      <BottomSheetTopBar
        title="Filters"
        left={
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="text-body text-accent active:opacity-60 no-tap-highlight min-h-[44px] -ml-2 px-2"
          >
            Cancel
          </button>
        }
      />
      <BottomSheetBody>
        <div className="flex flex-col gap-6 pt-2">
          {/* Type */}
          <section className="space-y-2">
            <SectionHeader>Type</SectionHeader>
            <ChipGroup
              options={ARTIFACT_TYPE_OPTIONS}
              isActive={(v) => draft.artifactTypes.includes(v)}
              onToggle={toggleArtifactType}
            />
            {draft.artifactTypes.length === 0 && (
              <p className="text-footnote text-label-tertiary">
                No selection means all types.
              </p>
            )}
          </section>

          {/* Helper */}
          <section className="space-y-2">
            <SectionHeader>Helper</SectionHeader>
            {agents.length === 0 ? (
              <p className="text-footnote text-label-tertiary">
                No helpers in the current results.
              </p>
            ) : (
              <ChipGroup
                options={agents.map((a) => ({ value: a, label: displayName(a) }))}
                isActive={(v) => draft.agents.includes(v)}
                onToggle={toggleAgent}
              />
            )}
            {agents.length > 0 && draft.agents.length === 0 && (
              <p className="text-footnote text-label-tertiary">
                No selection means all helpers.
              </p>
            )}
          </section>

          {/* Date */}
          <section className="space-y-2">
            <SectionHeader>Date range</SectionHeader>
            <SegmentedControl
              value={draft.dateRange}
              onChange={(v) => setDraftField("dateRange", v)}
              options={[
                { value: "any", label: "Any" },
                { value: "today", label: "Today" },
                { value: "week", label: "This week" },
                { value: "month", label: "This month" },
                { value: "custom", label: "Custom" },
              ]}
              ariaLabel="Date range"
            />
            {draft.dateRange === "custom" && (
              <div className="pt-1">
                <label
                  htmlFor="docs-filter-since"
                  className="block text-footnote text-label-secondary mb-1"
                >
                  Since
                </label>
                <Input
                  id="docs-filter-since"
                  type="date"
                  value={draft.customSince ?? ""}
                  onChange={(e) =>
                    setDraftField("customSince", e.target.value || null)
                  }
                  className="h-11 rounded-md bg-bg-elevated border-transparent text-body"
                />
              </div>
            )}
          </section>

          {/* Tags */}
          <section className="space-y-2">
            <SectionHeader>Tags</SectionHeader>
            <Input
              value={draft.tagsRaw}
              onChange={(e) => setDraftField("tagsRaw", e.target.value)}
              placeholder="critical, schedule, owner-review"
              className="h-11 rounded-md bg-bg-elevated border-transparent text-body"
              aria-label="Tags filter"
            />
            <p className="text-footnote text-label-tertiary">
              Comma-separated. Matches any document tagged with one or more.
            </p>
          </section>
        </div>
      </BottomSheetBody>
      <BottomSheetActionBar>
        <Button
          variant="ghost"
          className="h-[50px] flex-1 rounded-lg text-headline"
          onClick={reset}
          disabled={isDefault(draft)}
        >
          Reset
        </Button>
        <Button
          className="h-[50px] flex-1 rounded-lg text-headline"
          onClick={apply}
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

function ChipGroup<T extends string>({
  options,
  isActive,
  onToggle,
}: {
  options: { value: T; label: string }[];
  isActive: (v: T) => boolean;
  onToggle: (v: T) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((o) => {
        const active = isActive(o.value);
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onToggle(o.value)}
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
