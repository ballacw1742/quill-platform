"use client";

import * as React from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { ArtifactCard, ArtifactCardBody, ArtifactCardHeader } from "./shared/ArtifactCard";
import { MarkdownBlock } from "./shared/MarkdownBlock";
import { DataTable, type DataTableColumn } from "./shared/DataTable";

const MARKDOWN_KEYS = new Set([
  "body_markdown",
  "summary",
  "narrative",
  "description",
  "rationale",
  "notes",
  "basis_of_estimate",
  "basis_of_schedule",
]);

const SKIP_TOP_LEVEL = new Set(["artifact_type", "artifact_id", "parent_id"]);

function prettyKey(k: string): string {
  return k
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Expandable string field */
function ExpandableString({ value }: { value: string }) {
  const [expanded, setExpanded] = React.useState(false);
  const isLong = value.length > 200;
  const display = isLong && !expanded ? value.slice(0, 197) + "…" : value;
  return (
    <div>
      <span className="text-callout text-label-primary break-words">
        {display}
      </span>
      {isLong && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="ml-1.5 text-footnote text-accent no-tap-highlight active:opacity-60"
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}

/** Renders an array of objects as a compact table */
function ObjectArrayTable({ arr }: { arr: Record<string, unknown>[] }) {
  if (arr.length === 0) return <div className="text-callout text-label-tertiary">—</div>;
  const keys = Array.from(
    new Set(arr.flatMap((obj) => Object.keys(obj))),
  ).slice(0, 8); // cap columns

  const columns: DataTableColumn<Record<string, unknown>>[] = keys.map((k) => ({
    key: k,
    label: prettyKey(k),
    render: (row) => {
      const v = row[k];
      if (v == null) return "—";
      if (typeof v === "string") {
        return v.length > 80 ? v.slice(0, 77) + "…" : v;
      }
      if (typeof v === "number" || typeof v === "boolean") return String(v);
      return JSON.stringify(v).slice(0, 60);
    },
  }));

  return (
    <DataTable columns={columns} rows={arr} keyField={keys[0] ?? "id"} />
  );
}

/** Renders a nested object as indented key/value rows */
function NestedObject({ obj, depth = 0 }: { obj: Record<string, unknown>; depth?: number }) {
  return (
    <dl
      className={cn(
        "space-y-1.5",
        depth > 0 && "pl-4 border-l border-separator/30",
      )}
    >
      {Object.entries(obj).map(([k, v]) => (
        <ValueRow key={k} label={k} value={v} depth={depth} />
      ))}
    </dl>
  );
}

function ValueRow({
  label,
  value,
  depth = 0,
}: {
  label: string;
  value: unknown;
  depth?: number;
}) {
  const isMarkdown = MARKDOWN_KEYS.has(label) && typeof value === "string";

  if (isMarkdown && typeof value === "string") {
    return (
      <div className="py-1.5">
        <div className="text-caption-1 uppercase tracking-wider text-label-tertiary mb-1">
          {prettyKey(label)}
        </div>
        <MarkdownBlock content={value} />
      </div>
    );
  }

  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return (
      <div className="flex items-baseline gap-3 py-1 border-b border-separator/20 last:border-0">
        <dt className="text-callout text-label-secondary w-1/3 shrink-0">
          {prettyKey(label)}
        </dt>
        <dd className="flex-1 min-w-0">
          {typeof value === "string" ? (
            <ExpandableString value={value} />
          ) : (
            <span className="text-callout text-label-primary">{String(value)}</span>
          )}
        </dd>
      </div>
    );
  }

  if (Array.isArray(value)) {
    if (value.length === 0) return null;
    const isObjectArray = value.every(
      (v) => v && typeof v === "object" && !Array.isArray(v),
    );
    return (
      <div className="py-1.5">
        <div className="text-caption-1 uppercase tracking-wider text-label-tertiary mb-1">
          {prettyKey(label)} ({value.length})
        </div>
        {isObjectArray ? (
          <ObjectArrayTable arr={value as Record<string, unknown>[]} />
        ) : (
          <ul className="space-y-0.5 list-disc list-inside">
            {value.map((item, i) => (
              <li key={i} className="text-callout text-label-primary">
                {typeof item === "string"
                  ? item
                  : JSON.stringify(item).slice(0, 80)}
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  if (value && typeof value === "object" && !Array.isArray(value)) {
    return (
      <CollapsibleObject
        label={label}
        obj={value as Record<string, unknown>}
        depth={depth}
      />
    );
  }

  return null;
}

function CollapsibleObject({
  label,
  obj,
  depth,
}: {
  label: string;
  obj: Record<string, unknown>;
  depth: number;
}) {
  const [open, setOpen] = React.useState(depth === 0);
  return (
    <div className="py-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-callout text-label-secondary no-tap-highlight active:opacity-60"
      >
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 transition-transform",
            open && "rotate-180",
          )}
        />
        {prettyKey(label)}
      </button>
      {open && (
        <div className="mt-1.5">
          <NestedObject obj={obj} depth={depth + 1} />
        </div>
      )}
    </div>
  );
}

/**
 * GenericKeyValueView — clean key/value fallback for artifact types
 * we haven't built a custom renderer for yet.
 * Renders nested objects as indented sections, arrays as tables,
 * markdown fields as formatted prose. Never a raw JSON dump.
 */
export function GenericKeyValueView({
  artifact,
  mode: _mode = "view",
}: {
  artifact: Record<string, unknown>;
  mode?: "view" | "print";
}) {
  const artifactType = String(artifact.artifact_type ?? "unknown");
  const title = String(artifact.title ?? "Artifact");
  const summary = typeof artifact.summary === "string" ? artifact.summary : null;
  const bodyMd =
    typeof artifact.body_markdown === "string" ? artifact.body_markdown : null;

  const topFields = Object.entries(artifact).filter(
    ([k]) =>
      !SKIP_TOP_LEVEL.has(k) &&
      k !== "title" &&
      k !== "summary" &&
      k !== "body_markdown",
  );

  return (
    <div className="space-y-4">
      <ArtifactCard>
        <ArtifactCardHeader>
          <div className="text-footnote text-label-tertiary uppercase tracking-wider">
            {artifactType.replace(/_/g, " ")}
          </div>
          <h2 className="text-title-3 text-label-primary leading-snug mt-0.5">
            {title}
          </h2>
        </ArtifactCardHeader>
        {summary && (
          <ArtifactCardBody>
            <p className="text-callout text-label-primary leading-relaxed">
              {summary}
            </p>
          </ArtifactCardBody>
        )}
      </ArtifactCard>

      {bodyMd && (
        <ArtifactCard>
          <ArtifactCardHeader>
            <div className="text-caption-1 uppercase tracking-wider text-label-tertiary">
              Analysis
            </div>
          </ArtifactCardHeader>
          <ArtifactCardBody>
            <MarkdownBlock content={bodyMd} />
          </ArtifactCardBody>
        </ArtifactCard>
      )}

      <ArtifactCard>
        <ArtifactCardHeader>
          <div className="text-caption-1 uppercase tracking-wider text-label-tertiary">
            Details
          </div>
        </ArtifactCardHeader>
        <ArtifactCardBody>
          <dl className="space-y-0">
            {topFields.map(([k, v]) => (
              <ValueRow key={k} label={k} value={v} depth={0} />
            ))}
          </dl>
        </ArtifactCardBody>
      </ArtifactCard>
    </div>
  );
}
