"use client";

import * as React from "react";
import {
  ExternalLink,
  History,
  ChevronDown,
  ChevronUp,
  Edit2,
  Check,
  X,
  Sparkles,
  AlertTriangle,
  RotateCcw,
  Loader2,
} from "lucide-react";
import {
  BottomSheet,
  BottomSheetActionBar,
  BottomSheetBody,
  BottomSheetTopBar,
} from "@/components/ui/sheet";
import {
  useDeliverable,
  useDeliverableVersions,
  useUpdateDeliverable,
  useRollbackDeliverable,
  useCodevDeliverable,
  useResumeDeliverable,
  type Deliverable,
  type DeliverableVersion,
} from "@/lib/api";
import {
  detectContentKind,
  extractDocText,
  extractSheetRows,
  extractKVPairs,
  isCodevGate,
  diffContent,
} from "@/lib/deliverable-content";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

// ── Status config ──────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<string, { label: string; cls: string }> = {
  draft:          { label: "Draft",           cls: "text-label-secondary bg-bg-elevated" },
  in_progress:    { label: "In Progress",     cls: "text-blue-400 bg-blue-400/10" },
  awaiting_human: { label: "Awaiting Review", cls: "text-yellow-400 bg-yellow-400/10" },
  approved:       { label: "Approved",        cls: "text-green-400 bg-green-400/10" },
  published:      { label: "Published",       cls: "text-accent bg-accent/10" },
  superseded:     { label: "Superseded",      cls: "text-label-quaternary bg-bg-elevated" },
};

function statusCfg(status: string) {
  return STATUS_CONFIG[status] ?? { label: status, cls: "text-label-secondary bg-bg-elevated" };
}

// ── Content renderer — read mode ───────────────────────────────────────────

function DocContentView({ content }: { content: Record<string, unknown> }) {
  const text = extractDocText(content);
  if (!text) {
    return (
      <p className="text-callout text-label-quaternary italic">
        (no text content)
      </p>
    );
  }
  return (
    <pre className="text-callout text-label-primary whitespace-pre-wrap font-sans leading-relaxed">
      {text}
    </pre>
  );
}

function SheetContentView({ content }: { content: Record<string, unknown> }) {
  const rows = extractSheetRows(content);
  if (rows.length === 0) {
    return (
      <p className="text-callout text-label-quaternary italic">(empty sheet)</p>
    );
  }
  const [header, ...body] = rows;
  return (
    <div className="overflow-x-auto rounded-xl border border-separator/40">
      <table className="w-full text-caption-1 text-label-primary border-collapse">
        {header && (
          <thead>
            <tr className="border-b border-separator/40 bg-bg-elevated">
              {header.map((cell, i) => (
                <th
                  key={i}
                  className="px-3 py-2 text-left font-semibold text-label-secondary"
                >
                  {cell}
                </th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {body.map((row, ri) => (
            <tr
              key={ri}
              className={cn(
                "border-b border-separator/20",
                ri % 2 === 0 ? "bg-transparent" : "bg-bg-elevated/40",
              )}
            >
              {row.map((cell, ci) => (
                <td key={ci} className="px-3 py-2 align-top">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function KVContentView({ content }: { content: Record<string, unknown> }) {
  const pairs = extractKVPairs(content);
  if (pairs.length === 0) {
    return (
      <p className="text-callout text-label-quaternary italic">(no fields)</p>
    );
  }
  return (
    <div className="space-y-2">
      {pairs.map(({ key, value }) => (
        <div
          key={key}
          className="rounded-xl bg-bg-elevated border border-separator/30 px-3 py-2"
        >
          <p className="text-caption-2 font-semibold text-label-tertiary uppercase tracking-wide mb-0.5">
            {key.replace(/_/g, " ")}
          </p>
          <pre className="text-callout text-label-primary whitespace-pre-wrap font-sans">
            {value}
          </pre>
        </div>
      ))}
    </div>
  );
}

function ContentView({
  content,
}: {
  content: Record<string, unknown> | null | undefined;
}) {
  const kind = detectContentKind(content);
  if (kind === "empty" || !content) {
    return (
      <div className="rounded-xl bg-bg-elevated border border-separator/30 p-4">
        <p className="text-callout text-label-quaternary italic">
          No content yet.
        </p>
      </div>
    );
  }
  if (kind === "doc") return <DocContentView content={content} />;
  if (kind === "sheet") return <SheetContentView content={content} />;
  return <KVContentView content={content} />;
}

// ── Content editor — edit mode ────────────────────────────────────────────

function DocEditor({
  content,
  onChange,
}: {
  content: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
}) {
  const text = extractDocText(content);
  // Determine which key holds the primary text field
  const textKey =
    "markdown" in content
      ? "markdown"
      : "body_markdown" in content
        ? "body_markdown"
        : "text" in content
          ? "text"
          : "summary" in content
            ? "summary"
            : "text";

  return (
    <textarea
      className={cn(
        "w-full min-h-[240px] rounded-xl border border-separator/40 bg-bg-elevated",
        "px-3 py-2.5 text-callout text-label-primary font-sans leading-relaxed",
        "resize-none focus:outline-none focus:ring-1 focus:ring-accent",
      )}
      value={text}
      onChange={(e) => onChange({ ...content, [textKey]: e.target.value })}
      placeholder="Edit deliverable content…"
    />
  );
}

function SheetEditor({
  content,
  onChange,
}: {
  content: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
}) {
  const rows = extractSheetRows(content);
  const [localRows, setLocalRows] = React.useState(rows);

  const commit = (nextRows: string[][]) => {
    setLocalRows(nextRows);
    onChange({ ...content, rows: nextRows });
  };

  return (
    <div className="space-y-2">
      <p className="text-caption-2 text-label-tertiary">
        Edit cells inline. Add/remove rows as needed.
      </p>
      <div className="overflow-x-auto rounded-xl border border-separator/40">
        <table className="w-full text-caption-1 border-collapse">
          <tbody>
            {localRows.map((row, ri) => (
              <tr key={ri} className="border-b border-separator/20">
                {row.map((cell, ci) => (
                  <td key={ci} className="p-1">
                    <input
                      className={cn(
                        "w-full px-2 py-1 rounded bg-bg-elevated border border-separator/30",
                        "text-callout text-label-primary focus:outline-none focus:ring-1 focus:ring-accent",
                      )}
                      value={cell}
                      onChange={(e) => {
                        const next = localRows.map((r, i) =>
                          i === ri
                            ? r.map((c, j) => (j === ci ? e.target.value : c))
                            : r,
                        );
                        commit(next);
                      }}
                    />
                  </td>
                ))}
                <td className="p-1 w-8">
                  <button
                    type="button"
                    onClick={() => commit(localRows.filter((_, i) => i !== ri))}
                    className="text-label-quaternary hover:text-red-400 transition-colors"
                    aria-label="Remove row"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button
        type="button"
        onClick={() => {
          const cols = localRows[0]?.length ?? 1;
          commit([...localRows, Array(cols).fill("")]);
        }}
        className="text-caption-1 text-accent hover:underline"
      >
        + Add row
      </button>
    </div>
  );
}

function ContentEditor({
  content,
  onChange,
}: {
  content: Record<string, unknown> | null | undefined;
  onChange: (next: Record<string, unknown>) => void;
}) {
  const kind = detectContentKind(content);
  const safeContent = content ?? {};

  if (kind === "doc") {
    return <DocEditor content={safeContent} onChange={onChange} />;
  }
  if (kind === "sheet") {
    return <SheetEditor content={safeContent} onChange={onChange} />;
  }
  // JSON fallback
  const [rawJson, setRawJson] = React.useState(
    JSON.stringify(safeContent, null, 2),
  );
  const [parseError, setParseError] = React.useState<string | null>(null);

  return (
    <div className="space-y-1">
      <textarea
        className={cn(
          "w-full min-h-[200px] rounded-xl border font-mono text-xs text-label-primary bg-bg-elevated",
          "px-3 py-2.5 resize-none focus:outline-none focus:ring-1",
          parseError
            ? "border-red-400/60 focus:ring-red-400"
            : "border-separator/40 focus:ring-accent",
        )}
        value={rawJson}
        onChange={(e) => {
          setRawJson(e.target.value);
          try {
            const parsed = JSON.parse(e.target.value) as Record<string, unknown>;
            setParseError(null);
            onChange(parsed);
          } catch {
            setParseError("Invalid JSON");
          }
        }}
        placeholder="{}"
      />
      {parseError && (
        <p className="text-caption-2 text-red-400">{parseError}</p>
      )}
    </div>
  );
}

// ── Version history panel ─────────────────────────────────────────────────

function VersionHistoryPanel({
  deliverableId,
  currentVersion,
}: {
  deliverableId: string;
  currentVersion: number;
}) {
  const { data, isLoading } = useDeliverableVersions(deliverableId);
  const rollback = useRollbackDeliverable();
  const [confirming, setConfirming] = React.useState<number | null>(null);

  const items = data?.items ?? [];

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-4">
        <Loader2 className="h-4 w-4 animate-spin text-label-quaternary" />
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <p className="text-callout text-label-quaternary italic py-2">
        No prior versions.
      </p>
    );
  }

  const handleRollback = async (v: DeliverableVersion) => {
    if (confirming !== v.version) {
      setConfirming(v.version);
      return;
    }
    setConfirming(null);
    try {
      await rollback.mutateAsync({ id: deliverableId, to_version: v.version });
      toast.success(`Rolled back to v${v.version}`);
    } catch {
      toast.error("Rollback failed — try again");
    }
  };

  return (
    <div className="space-y-1.5">
      {items.map((v) => {
        const isCurrent = v.version === currentVersion;
        const isConfirming = confirming === v.version;
        const { label, cls } = statusCfg(v.status);
        return (
          <div
            key={v.id}
            className={cn(
              "flex items-center gap-2 rounded-xl px-3 py-2 border",
              isCurrent
                ? "border-accent/40 bg-accent/5"
                : "border-separator/30 bg-bg-elevated",
            )}
          >
            <span className="text-caption-2 font-bold text-label-tertiary tabular-nums w-5">
              v{v.version}
            </span>
            <span
              className={cn(
                "text-caption-2 font-semibold rounded-full px-1.5 py-0.5 shrink-0",
                cls,
              )}
            >
              {label}
            </span>
            <span className="text-caption-2 text-label-tertiary flex-1 truncate">
              {v.title}
            </span>
            <span className="text-caption-2 text-label-quaternary shrink-0 capitalize">
              {v.change_action.replace(/_/g, " ")}
            </span>
            <span className="text-caption-2 text-label-quaternary shrink-0">
              {new Date(v.created_at).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
              })}
            </span>
            {!isCurrent && (
              <button
                type="button"
                disabled={rollback.isPending}
                onClick={() => handleRollback(v)}
                className={cn(
                  "flex items-center gap-1 shrink-0 rounded-lg px-2 py-1 text-caption-2 font-semibold transition-colors",
                  isConfirming
                    ? "bg-yellow-400/15 text-yellow-400 hover:bg-yellow-400/25"
                    : "bg-bg-elevated text-label-tertiary hover:text-label-primary",
                )}
              >
                {rollback.isPending && confirming === v.version ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <RotateCcw className="h-3 w-3" />
                )}
                {isConfirming ? "Confirm?" : "Rollback"}
              </button>
            )}
            {isCurrent && (
              <span className="text-caption-2 font-semibold text-accent shrink-0">
                current
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Co-develop panel ───────────────────────────────────────────────────────

type CodevProposal = {
  proposed_content: Record<string, unknown>;
  proposed_summary: string | null;
  based_on_version: number;
};

function ProposalPreview({
  current,
  proposal,
}: {
  current: Record<string, unknown> | null | undefined;
  proposal: CodevProposal;
}) {
  const { before, after } = diffContent(current, proposal.proposed_content);
  const [tab, setTab] = React.useState<"after" | "diff">("after");

  return (
    <div className="space-y-3">
      {proposal.proposed_summary && (
        <div className="rounded-xl bg-accent/5 border border-accent/20 px-3 py-2">
          <p className="text-caption-2 font-semibold text-accent mb-0.5">
            AI Summary
          </p>
          <p className="text-callout text-label-primary">
            {proposal.proposed_summary}
          </p>
        </div>
      )}
      <div className="flex gap-2 border-b border-separator/30 pb-1">
        <button
          type="button"
          onClick={() => setTab("after")}
          className={cn(
            "text-caption-1 font-semibold pb-1 border-b-2 transition-colors",
            tab === "after"
              ? "border-accent text-accent"
              : "border-transparent text-label-tertiary",
          )}
        >
          Proposed
        </button>
        <button
          type="button"
          onClick={() => setTab("diff")}
          className={cn(
            "text-caption-1 font-semibold pb-1 border-b-2 transition-colors",
            tab === "diff"
              ? "border-accent text-accent"
              : "border-transparent text-label-tertiary",
          )}
        >
          Before / After
        </button>
      </div>
      {tab === "after" && (
        <ContentView content={proposal.proposed_content} />
      )}
      {tab === "diff" && (
        <div className="grid grid-cols-2 gap-2">
          <div>
            <p className="text-caption-2 font-semibold text-label-tertiary mb-1">
              Before
            </p>
            <pre className="text-caption-2 text-label-secondary whitespace-pre-wrap font-mono bg-bg-elevated rounded-xl p-3 border border-separator/30 overflow-x-auto">
              {before}
            </pre>
          </div>
          <div>
            <p className="text-caption-2 font-semibold text-accent mb-1">
              After
            </p>
            <pre className="text-caption-2 text-label-primary whitespace-pre-wrap font-mono bg-accent/5 rounded-xl p-3 border border-accent/20 overflow-x-auto">
              {after}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

function CoDevelopPanel({
  deliverable,
  onEditProposal,
}: {
  deliverable: Deliverable;
  onEditProposal: (content: Record<string, unknown>) => void;
}) {
  const [prompt, setPrompt] = React.useState("");
  const codev = useCodevDeliverable();
  const resume = useResumeDeliverable();
  const [proposal, setProposal] = React.useState<CodevProposal | null>(null);

  const handleAskAI = async () => {
    if (!prompt.trim()) return;
    try {
      const result = await codev.mutateAsync({
        id: deliverable.id,
        prompt: prompt.trim(),
        current_content: deliverable.content ?? undefined,
      });
      setProposal(result);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      toast.error(`AI revision failed — your deliverable is unchanged`, {
        description: msg,
      });
    }
  };

  const handleAccept = async () => {
    if (!proposal) return;
    try {
      await resume.mutateAsync({
        id: deliverable.id,
        content: proposal.proposed_content,
        resume_chain: true,
      });
      toast.success("Co-developed version accepted");
      setProposal(null);
      setPrompt("");
    } catch {
      toast.error("Failed to accept proposal — try again");
    }
  };

  const handleEditThenAccept = () => {
    if (!proposal) return;
    onEditProposal(proposal.proposed_content);
    setProposal(null);
  };

  const handleDiscard = () => {
    setProposal(null);
  };

  return (
    <div className="space-y-3">
      {!proposal ? (
        <>
          <p className="text-caption-1 text-label-secondary">
            Describe what you'd like the AI to revise, add, or restructure in
            this deliverable.
          </p>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="e.g. 'Confirm scope assumptions for mechanical scope only' or 'Resolve the drawing conflict in section 3'…"
            className={cn(
              "w-full min-h-[100px] rounded-xl border border-separator/40 bg-bg-elevated",
              "px-3 py-2.5 text-callout text-label-primary font-sans leading-relaxed",
              "resize-none focus:outline-none focus:ring-1 focus:ring-accent",
            )}
          />
          <button
            type="button"
            disabled={!prompt.trim() || codev.isPending}
            onClick={handleAskAI}
            className={cn(
              "w-full flex items-center justify-center gap-2 rounded-xl py-3",
              "text-callout font-semibold transition-colors",
              !prompt.trim() || codev.isPending
                ? "bg-bg-elevated text-label-quaternary cursor-not-allowed"
                : "bg-accent text-white hover:bg-accent/90 active:bg-accent/80",
            )}
          >
            {codev.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                AI is revising…
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4" />
                Ask AI to Revise
              </>
            )}
          </button>
        </>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-caption-1 font-semibold text-accent">
            <Sparkles className="h-4 w-4" />
            AI Proposal (based on v{proposal.based_on_version})
          </div>
          <ProposalPreview
            current={deliverable.content}
            proposal={proposal}
          />
          <div className="flex gap-2">
            <button
              type="button"
              disabled={resume.isPending}
              onClick={handleAccept}
              className={cn(
                "flex-1 flex items-center justify-center gap-2 rounded-xl py-2.5",
                "text-callout font-semibold transition-colors",
                "bg-green-500/90 text-white hover:bg-green-500 active:bg-green-600",
              )}
            >
              {resume.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Check className="h-4 w-4" />
              )}
              Accept
            </button>
            <button
              type="button"
              onClick={handleEditThenAccept}
              className={cn(
                "flex-1 flex items-center justify-center gap-2 rounded-xl py-2.5",
                "text-callout font-semibold transition-colors",
                "bg-bg-elevated border border-separator/40 text-label-primary hover:bg-bg-tertiary",
              )}
            >
              <Edit2 className="h-4 w-4" />
              Edit then Accept
            </button>
            <button
              type="button"
              onClick={handleDiscard}
              className={cn(
                "flex items-center justify-center gap-1.5 rounded-xl px-3 py-2.5",
                "text-callout font-semibold transition-colors",
                "text-label-tertiary hover:text-red-400",
              )}
              aria-label="Discard proposal"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <button
            type="button"
            onClick={() => setProposal(null)}
            className="text-caption-1 text-label-tertiary hover:text-label-primary transition-colors"
          >
            ← Try a different prompt
          </button>
        </div>
      )}
    </div>
  );
}

// ── Main sheet ─────────────────────────────────────────────────────────────

type Panel = "content" | "history" | "codev";

export type DeliverableDetailSheetProps = {
  /** Deliverable id to show, or null/undefined when closed */
  deliverableId: string | null;
  onClose: () => void;
};

export function DeliverableDetailSheet({
  deliverableId,
  onClose,
}: DeliverableDetailSheetProps) {
  const { data: deliverable, isLoading } = useDeliverable(
    deliverableId ?? "",
    { enabled: Boolean(deliverableId) },
  );
  const updateDeliverable = useUpdateDeliverable();

  const [activePanel, setActivePanel] = React.useState<Panel>("content");
  const [editMode, setEditMode] = React.useState(false);
  const [editContent, setEditContent] = React.useState<
    Record<string, unknown> | null
  >(null);

  // Reset edit state when the deliverable changes
  React.useEffect(() => {
    setEditMode(false);
    setEditContent(null);
    setActivePanel("content");
  }, [deliverableId]);

  const handleSave = async () => {
    if (!deliverable || editContent === null) return;
    try {
      await updateDeliverable.mutateAsync({
        id: deliverable.id,
        patch: { content: editContent, change_action: "human_edited" },
      });
      toast.success("Saved — new version created");
      setEditMode(false);
      setEditContent(null);
    } catch {
      toast.error("Save failed — try again");
    }
  };

  const handleCancelEdit = () => {
    setEditMode(false);
    setEditContent(null);
  };

  const handleStartEdit = () => {
    setEditContent(deliverable?.content ?? null);
    setEditMode(true);
    setActivePanel("content");
  };

  // Load a co-dev proposal into the editor (Edit-then-accept path)
  const handleEditProposal = (proposedContent: Record<string, unknown>) => {
    setEditContent(proposedContent);
    setEditMode(true);
    setActivePanel("content");
  };

  const open = Boolean(deliverableId);
  const d = deliverable;
  const codevGate = d
    ? isCodevGate(d.status, d.meta)
    : false;

  return (
    <BottomSheet
      open={open}
      onOpenChange={(o) => { if (!o) onClose(); }}
      fullHeight
      ariaLabel="Deliverable detail"
    >
      <BottomSheetTopBar
        title={
          isLoading
            ? "Loading…"
            : d?.title ?? "Deliverable"
        }
        right={
          !editMode ? (
            <button
              type="button"
              onClick={handleStartEdit}
              className="flex items-center gap-1.5 text-callout text-accent font-semibold"
              aria-label="Edit deliverable"
            >
              <Edit2 className="h-4 w-4" />
              Edit
            </button>
          ) : (
            <button
              type="button"
              onClick={handleCancelEdit}
              className="text-callout text-label-tertiary font-semibold"
            >
              Cancel
            </button>
          )
        }
      />

      <BottomSheetBody>
        {isLoading && (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-label-quaternary" />
          </div>
        )}

        {!isLoading && d && (
          <div className="space-y-4">
            {/* ── Co-dev HITL gate banner ── */}
            {codevGate && (
              <div className="flex items-start gap-3 rounded-2xl bg-yellow-400/10 border border-yellow-400/30 px-4 py-3">
                <AlertTriangle className="h-5 w-5 text-yellow-400 shrink-0 mt-0.5" />
                <div>
                  <p className="text-callout font-semibold text-yellow-400">
                    Awaiting your input — co-develop this deliverable
                  </p>
                  <p className="text-caption-1 text-label-secondary mt-0.5">
                    The pipeline is paused here. Use the Co-develop panel to
                    revise the content with AI, then accept to resume.
                  </p>
                  <button
                    type="button"
                    onClick={() => setActivePanel("codev")}
                    className="mt-1.5 text-caption-1 font-semibold text-yellow-400 hover:underline"
                  >
                    Go to Co-develop →
                  </button>
                </div>
              </div>
            )}

            {/* ── Meta strip ── */}
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={cn(
                  "text-caption-1 font-semibold rounded-full px-2.5 py-0.5",
                  statusCfg(d.status).cls,
                )}
              >
                {statusCfg(d.status).label}
              </span>
              <span className="text-caption-2 font-bold text-label-quaternary tabular-nums rounded-full px-2 py-0.5 bg-bg-elevated border border-separator/30">
                v{d.version}
              </span>
              <span className="text-caption-2 text-label-tertiary">
                {d.deliverable_type.replace(/_/g, " ")}
              </span>
              {d.stage_key && (
                <span className="text-caption-2 text-label-quaternary">
                  {d.stage_key.replace(/_/g, " ")}
                </span>
              )}
              <span className="text-caption-2 text-label-quaternary">
                {d.module_key}
              </span>
            </div>

            {/* ── Drive link ── */}
            {d.drive_url ? (
              <a
                href={d.drive_url}
                target="_blank"
                rel="noopener noreferrer"
                className={cn(
                  "flex items-center gap-2 rounded-xl px-3 py-2.5",
                  "bg-bg-elevated border border-separator/40",
                  "text-callout font-semibold text-accent hover:bg-bg-tertiary transition-colors",
                )}
              >
                <ExternalLink className="h-4 w-4 shrink-0" />
                Open in Google{" "}
                {d.deliverable_type === "sheet" ? "Sheets" : "Docs"}
              </a>
            ) : (
              <div className="flex items-center gap-2 rounded-xl px-3 py-2.5 bg-bg-elevated border border-separator/30">
                <span className="text-caption-2 text-label-quaternary italic">
                  Local record — no Drive doc
                </span>
              </div>
            )}

            {/* ── Panel tabs ── */}
            <div className="flex gap-0 rounded-xl border border-separator/40 overflow-hidden">
              {(
                [
                  { id: "content" as Panel, label: "Content" },
                  { id: "history" as Panel, label: "History", icon: History },
                  { id: "codev" as Panel, label: "Co-develop", icon: Sparkles },
                ] as const
              ).map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => {
                    setActivePanel(id);
                    if (id !== "content") setEditMode(false);
                  }}
                  className={cn(
                    "flex-1 flex items-center justify-center gap-1.5 py-2 text-caption-1 font-semibold transition-colors border-r border-separator/30 last:border-r-0",
                    activePanel === id
                      ? "bg-accent/10 text-accent"
                      : "text-label-tertiary hover:text-label-primary",
                  )}
                >
                  {Icon && <Icon className="h-3.5 w-3.5" />}
                  {label}
                </button>
              ))}
            </div>

            {/* ── Content panel ── */}
            {activePanel === "content" && (
              <div className="space-y-3">
                {editMode ? (
                  <ContentEditor
                    content={editContent ?? d.content}
                    onChange={setEditContent}
                  />
                ) : (
                  <ContentView content={d.content} />
                )}
              </div>
            )}

            {/* ── History panel ── */}
            {activePanel === "history" && (
              <VersionHistoryPanel
                deliverableId={d.id}
                currentVersion={d.version}
              />
            )}

            {/* ── Co-develop panel ── */}
            {activePanel === "codev" && (
              <CoDevelopPanel
                deliverable={d}
                onEditProposal={handleEditProposal}
              />
            )}
          </div>
        )}
      </BottomSheetBody>

      {/* ── Action bar (edit mode only) ── */}
      {editMode && (
        <BottomSheetActionBar>
          <button
            type="button"
            onClick={handleCancelEdit}
            className={cn(
              "flex-1 rounded-xl py-3 text-callout font-semibold border border-separator/40",
              "text-label-primary bg-bg-elevated hover:bg-bg-tertiary transition-colors",
            )}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={updateDeliverable.isPending || editContent === null}
            className={cn(
              "flex-1 flex items-center justify-center gap-2 rounded-xl py-3",
              "text-callout font-semibold transition-colors",
              updateDeliverable.isPending || editContent === null
                ? "bg-bg-elevated text-label-quaternary cursor-not-allowed"
                : "bg-accent text-white hover:bg-accent/90",
            )}
          >
            {updateDeliverable.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Saving…
              </>
            ) : (
              <>
                <Check className="h-4 w-4" />
                Save
              </>
            )}
          </button>
        </BottomSheetActionBar>
      )}
    </BottomSheet>
  );
}
