"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  ArrowUpFromLine,
  Check,
  ChevronDown,
  Clock,
  ExternalLink,
  X,
  History as HistoryIcon,
  Loader2,
} from "lucide-react";
import {
  BottomSheet,
  BottomSheetActionBar,
  BottomSheetBody,
  BottomSheetTopBar,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { BiometricPrompt } from "@/components/ui/biometric-prompt";
import { EditPayloadDialog } from "@/components/approval/EditPayloadDialog";
import { JsonBlock } from "@/components/approval/JsonBlock";
import { ArtifactView } from "@/components/artifacts/ArtifactView";
import { useApproval, useAudit, useDecide } from "@/lib/api";
import type { ApprovalItem } from "@/lib/schemas";
import { getChainOutputs } from "@/lib/schemas";
import { ChainOutputsPanel } from "./ChainOutputsPanel";
import type { ActionIntent } from "@/lib/auth";
import { formatDistanceToNowStrict } from "date-fns";
import { toast } from "sonner";
import { cn, shortHash } from "@/lib/utils";
import { AgentBadge } from "./AgentBadge";
import { FlagChips } from "./FlagChips";
import { HelpHint } from "@/components/ui/help-hint";
import { LANE_META } from "./laneMeta";
import {
  displayName,
  displayConfidence,
  displayWorkflow,
  displayPriority,
} from "@/lib/agent-meta";

/**
 * Build a plain-English title for the approval, per COPY_GUIDE
 * §"Detail screen rewrites":
 *   "<Workflow> — <key reference>" (e.g. "Sort RFI — RFI 247").
 * Falls back to just the workflow if no source ref is available.
 */
function buildPlainTitle(item: ApprovalItem): string {
  const action = displayWorkflow(item.workflow);
  // First non-empty source ref is the natural "key reference".
  const firstRef = item.context?.sources?.find((s) => s.ref)?.ref;
  return firstRef ? `${action} — ${firstRef}` : action;
}

/**
 * One-line summary for the lede block.
 * Prefer the agent's `summary` field; otherwise fall back to a trimmed
 * rationale; otherwise fall back to a synthesized line from the proposed
 * action. Never returns an empty string.
 */
function buildLedeSummary(item: ApprovalItem): string {
  if (item.summary && item.summary.trim()) return item.summary.trim();
  if (item.rationale && item.rationale.trim()) {
    const r = item.rationale.trim();
    // First sentence, capped at ~180 chars.
    const firstStop = r.search(/[.!?]\s/);
    const trimmed = firstStop > 30 ? r.slice(0, firstStop + 1) : r;
    return trimmed.length > 200 ? trimmed.slice(0, 197) + "…" : trimmed;
  }
  const target = item.proposed_action.target_system ?? "draft only";
  return `${item.proposed_action.kind} → ${target}`;
}

/**
 * Recommended-action sentence shown right under the summary. We synthesize
 * this from the proposed action so it reads like a recommendation rather
 * than raw payload data.
 */
function buildRecommendedAction(item: ApprovalItem): string {
  const target = item.proposed_action.target_system;
  const kind = item.proposed_action.kind;
  // Common action shapes — keep this simple, fall back generically.
  if (kind?.toLowerCase().includes("route") && target) {
    return `Route this to ${target}.`;
  }
  if (kind?.toLowerCase().includes("draft")) {
    return target ? `Draft a response in ${target}.` : `Draft a response.`;
  }
  if (kind?.toLowerCase().includes("escalate")) {
    return `Escalate to ${target ?? "the right reviewer"}.`;
  }
  if (kind?.toLowerCase().includes("flag")) {
    return `Flag this for review.`;
  }
  if (target) {
    return `${prettyKind(kind)} in ${target}.`;
  }
  return `${prettyKind(kind)}.`;
}

function prettyKind(kind: string | undefined | null): string {
  if (!kind) return "Take action";
  const cleaned = kind.replace(/[._-]+/g, " ").replace(/\s+/g, " ").trim();
  if (!cleaned) return "Take action";
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1).toLowerCase();
}

/**
 * ApprovalDetailSheet — bottom sheet that replaces the standalone
 * /approvals/[id] page on mobile.
 *
 * MOBILE_UX_SPEC.md §"Approval detail sheet":
 *   ┌─────────────────────────────────────────┐
 *   │  drag handle                            │
 *   │  Cancel        Approval        ⋯        │
 *   │                                         │
 *   │  Hero: agent's headline recommendation  │
 *   │  Triage data table                      │
 *   │  ────                                   │
 *   │  CONTEXT                                │
 *   │  • source artifact rows (tappable)     │
 *   │  Reasoning (italic, label-secondary)    │
 *   │  ────                                   │
 *   │  AUDIT TRAIL                            │
 *   │  Created 2h ago · agent:rfi-triage      │
 *   ├─────────────────────────────────────────┤
 *   │  [Reject]  [Edit]      [Approve]        │
 *   └─────────────────────────────────────────┘
 */

type DecisionMode = "approve" | "reject" | "escalate" | "edit-then-approve";

export function ApprovalDetailSheet({
  approvalId,
  onClose,
}: {
  approvalId: string | null;
  onClose: () => void;
}) {
  const open = !!approvalId;
  const { data: item, isLoading } = useApproval(approvalId ?? "");
  const { data: audit = [] } = useAudit();
  const decide = useDecide();
  const router = useRouter();

  const [editOpen, setEditOpen] = React.useState(false);
  const [editedPayload, setEditedPayload] = React.useState<
    Record<string, unknown> | null
  >(null);
  const [reason, setReason] = React.useState("");
  const [reasonOpen, setReasonOpen] = React.useState<DecisionMode | null>(null);
  const [biometricOpen, setBiometricOpen] = React.useState(false);
  const [pendingMode, setPendingMode] = React.useState<DecisionMode | null>(null);
  const [showRawJson, setShowRawJson] = React.useState(false);

  // Reset transient state when sheet closes.
  React.useEffect(() => {
    if (!open) {
      setEditOpen(false);
      setEditedPayload(null);
      setReason("");
      setReasonOpen(null);
      setBiometricOpen(false);
      setPendingMode(null);
      setShowRawJson(false);
    }
  }, [open]);

  const trail = React.useMemo(
    () =>
      (audit ?? [])
        .filter((e) => e.approval_id === approvalId)
        .sort((a, b) => a.seq - b.seq),
    [audit, approvalId],
  );

  const isPending = item?.status === "pending";

  const startApprove = () => {
    setPendingMode("approve");
    setBiometricOpen(true);
  };
  const startReject = () => setReasonOpen("reject");
  // Escalate is in the kebab menu (not the primary action bar).

  const onEditConfirmed = (payload: Record<string, unknown>) => {
    setEditedPayload(payload);
    setEditOpen(false);
    setPendingMode("edit-then-approve");
    setBiometricOpen(true);
  };

  const onReasonContinue = () => {
    if (!reasonOpen) return;
    if (reasonOpen === "reject" && !reason.trim()) {
      toast.error("Add a short reason before sending it back.");
      return;
    }
    setPendingMode(reasonOpen);
    setReasonOpen(null);
    setBiometricOpen(true);
  };

  const buildIntent = React.useCallback((): ActionIntent | null => {
    if (!item || !pendingMode) return null;
    const apiDecision: ActionIntent["decision"] =
      pendingMode === "approve"
        ? "approve"
        : pendingMode === "edit-then-approve"
          ? "edit_then_approve"
          : pendingMode === "reject"
            ? "reject"
            : "escalate";
    return {
      approval_id: item.approval_id,
      decision: apiDecision,
      edits: editedPayload,
      rejection_reason:
        pendingMode === "reject" || pendingMode === "escalate"
          ? reason || null
          : null,
      escalate_to_lane: null,
    };
  }, [item, pendingMode, editedPayload, reason]);

  const onBiometricSuccess = async (assertion?: { auth_assertion: string }) => {
    if (!item || !pendingMode) return;
    const wire =
      pendingMode === "approve" || pendingMode === "edit-then-approve"
        ? "approved"
        : pendingMode === "reject"
          ? "rejected"
          : "escalated";
    try {
      await decide.mutateAsync(
        {
          id: item.approval_id,
          decision: wire,
          reason: wire === "approved" ? undefined : reason || undefined,
          edited_payload: editedPayload ?? undefined,
          passkey_assertion: assertion?.auth_assertion,
        },
        {
          onSuccess: () => {
            // Per COPY_GUIDE: brief, direct confirmation.
            toast.success("Decision saved.");
            onClose();
          },
          // Error toast is handled centrally by useDecide's onError in api.ts.
        },
      );
    } catch (e) {
      // useDecide.onError already showed a differentiated toast; just log.
      // eslint-disable-next-line no-console
      console.error("approval decision failed", e);
    }
  };

  return (
    <>
      <BottomSheet
        open={open && !biometricOpen}
        onOpenChange={(v) => {
          if (!v) onClose();
        }}
        ariaLabel="Approval detail"
        fullHeight
      >
        <BottomSheetTopBar
          title={item ? "Item details" : isLoading ? " " : "Not found"}
          left={
            <button
              type="button"
              onClick={onClose}
              className="text-body text-accent active:opacity-60 no-tap-highlight min-h-[44px] -ml-2 px-2"
            >
              Cancel
            </button>
          }
          right={
            item ? (
              <KebabMenu
                onShowJson={() => setShowRawJson(true)}
                onEscalate={() => setReasonOpen("escalate")}
                onOpenStandalone={() =>
                  router.push(`/approvals/${item.approval_id}`)
                }
              />
            ) : null
          }
        />
        <BottomSheetBody>
          {isLoading && <DetailSkeleton />}
          {!isLoading && !item && (
            <div className="py-12 text-center text-body text-label-secondary">
              Couldn’t load this item.
            </div>
          )}
          {item && (
            <DetailContent
              item={item}
              showRawJson={showRawJson}
              trail={trail}
            />
          )}
          {item && reasonOpen && (
            <div className="mt-4 rounded-lg bg-bg-elevated p-3">
              <div className="text-subhead text-label-secondary mb-1">
                {reasonOpen === "reject"
                  ? "Why send it back?"
                  : "Why escalate?"}
              </div>
              <textarea
                className="w-full min-h-[88px] rounded-md border border-separator-opaque bg-bg-tertiary px-3 py-2 text-body text-label-primary"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder={
                  reasonOpen === "reject"
                    ? "Required — what's wrong?"
                    : "Optional — context for the second signer."
                }
                rows={4}
              />
              <div className="mt-2 flex justify-end gap-2">
                <Button
                  variant="ghost"
                  className="h-11 rounded-md text-body"
                  onClick={() => setReasonOpen(null)}
                >
                  Cancel
                </Button>
                <Button
                  className="h-11 rounded-md text-body"
                  variant={reasonOpen === "reject" ? "destructive" : "warning"}
                  onClick={onReasonContinue}
                  disabled={reasonOpen === "reject" && !reason.trim()}
                >
                  Continue
                </Button>
              </div>
            </div>
          )}
        </BottomSheetBody>

        {item && isPending && !reasonOpen && (
          <BottomSheetActionBar>
            <Button
              variant="ghost"
              onClick={startReject}
              className="h-[50px] flex-1 rounded-lg text-headline text-danger"
              disabled={decide.isPending}
            >
              <X className="h-4 w-4" /> Send back
            </Button>
            <Button
              variant="default"
              onClick={startApprove}
              className="h-[50px] flex-[1.4] rounded-lg text-headline"
              disabled={decide.isPending}
            >
              {decide.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Check className="h-4 w-4" />
              )}
              Approve
            </Button>
          </BottomSheetActionBar>
        )}

        {item && !isPending && (
          <BottomSheetActionBar>
            <div className="flex-1 text-center text-callout text-label-secondary py-3">
              Already {item.status}
              {item.decided_at &&
                ` · ${new Date(item.decided_at).toLocaleString()}`}
            </div>
          </BottomSheetActionBar>
        )}
      </BottomSheet>

      {/* Edit-payload sheet wraps the existing simple JSON editor. The dialog
          renders as a Radix Dialog above the BottomSheet (z-stacking is
          fine — the BottomSheet uses z-50, Radix Dialogs default to z-50
          too but the EditPayloadDialog uses its own portal). */}
      {item && (
        <EditPayloadDialog
          open={editOpen}
          onOpenChange={setEditOpen}
          original={item.proposed_action.payload}
          onConfirm={onEditConfirmed}
        />
      )}

      <BiometricPrompt
        open={biometricOpen}
        onOpenChange={(v) => {
          setBiometricOpen(v);
          if (!v) setPendingMode(null);
        }}
        title={
          pendingMode === "approve" || pendingMode === "edit-then-approve"
            ? "Confirm approval"
            : pendingMode === "reject"
              ? "Confirm send-back"
              : pendingMode === "escalate"
                ? "Confirm escalation"
                : "Confirm"
        }
        description={
          item
            ? pendingMode === "approve" || pendingMode === "edit-then-approve"
              ? item.proposed_action.target_system
                ? `Once you confirm, this runs in ${item.proposed_action.target_system}.`
                : "This marks the item approved (nothing is sent yet)."
              : pendingMode === "reject"
                ? `Send ${humanRef(item)} back.`
                : `Send ${humanRef(item)} to a second signer.`
            : "Confirm with your passkey."
        }
        actionIntent={buildIntent() ?? undefined}
        onConfirm={onBiometricSuccess}
        destructive={pendingMode === "reject"}
      />
    </>
  );
}

/* ── Inner content blocks ───────────────────────────────────────────────── */

function DetailContent({
  item,
  showRawJson,
  trail,
}: {
  item: ApprovalItem;
  showRawJson: boolean;
  trail: Array<{ seq: number; ts: string; action: string; actor: string; hash: string; notes?: string }>;
}) {
  const lane = LANE_META[item.lane];
  const age = formatDistanceToNowStrict(new Date(item.created_at), {
    addSuffix: true,
  });

  const title = buildPlainTitle(item);
  const lede = buildLedeSummary(item);
  const recommendation = buildRecommendedAction(item);
  const confidencePct = displayConfidence(item.confidence ?? 0, true); // "89% confident"

  return (
    <div className="space-y-5">
      {/* ── Lede block ──────────────────────────────────────────── */}
      <section className="space-y-2">
        <div className="flex items-start gap-3">
          <AgentBadge agentId={item.agent_id} className="h-9 w-9" />
          <div className="min-w-0 flex-1">
            <h2 className="text-title-3 text-label-primary leading-tight">
              {title}
            </h2>
            <div className="mt-1 text-footnote text-label-tertiary">
              {displayName(item.agent_id)} · {lane?.label ?? ""}
            </div>
          </div>
        </div>
        <p className="text-body text-label-primary leading-relaxed">{lede}</p>
        <div className="rounded-lg bg-bg-elevated p-3">
          <div className="text-caption-1 uppercase tracking-wider text-label-tertiary mb-1">
            Recommended action
          </div>
          <div className="text-callout text-label-primary">
            {recommendation}
            {confidencePct && (
              <span className="text-label-secondary inline-flex items-center gap-1">
                {" "}({confidencePct})
                <HelpHint
                  term="confidence"
                  ariaLabel="What does the confidence percentage mean?"
                />
              </span>
            )}
          </div>
        </div>
        {(item.escalations?.length ?? 0) > 0 ? (
          <div className="flex items-center gap-2">
            <FlagChips item={item} />
            <HelpHint
              term="escalations"
              ariaLabel="Why is this flagged?"
            />
          </div>
        ) : (
          <FlagChips item={item} />
        )}
      </section>

      {/* ── Artifact renderer ────────────────────────────────────── */}
      {(() => {
        const artifact = (
          item.proposed_action.payload as Record<string, unknown>
        )?.artifact as Record<string, unknown> | undefined;
        if (artifact?.artifact_type) {
          return (
            <ArtifactView
              artifact={artifact}
              mode="view"
              approvalId={item.approval_id}
            />
          );
        }
        return null;
      })()}

      {/* ── Live draft (chained agent outputs) — Phase F.1 ───────── */}
      {(() => {
        const chain = getChainOutputs(item.proposed_action.payload);
        return chain ? <ChainOutputsPanel chain={chain} /> : null;
      })()}

      {/* ── Why panel — collapsed by default ────────────────────── */}
      <WhyPanel item={item} />

      {/* ── Citations / sources ─────────────────────────────────── */}
      {item.context.sources.length > 0 && (
        <section className="space-y-2">
          <div className="text-caption-1 uppercase tracking-wider text-label-secondary px-1">
            Citations
          </div>
          <ul className="overflow-hidden rounded-lg bg-bg-tertiary divide-y divide-separator/40">
            {item.context.sources.map((s, i) => {
              const inner = (
                <div className="flex items-center gap-3 px-4 py-3 min-h-[56px]">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-bg-elevated text-label-secondary">
                    <ExternalLink className="h-4 w-4" />
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-callout text-label-primary truncate">
                      <span className="text-label-secondary">{s.kind}</span>{" "}
                      <span className="font-mono">{s.ref}</span>
                    </div>
                    {s.excerpt && (
                      <div className="text-footnote text-label-tertiary line-clamp-2">
                        “{s.excerpt}”
                      </div>
                    )}
                  </div>
                </div>
              );
              if (s.url) {
                return (
                  <li key={i}>
                    <a
                      href={s.url}
                      target="_blank"
                      rel="noreferrer"
                      className="block no-tap-highlight active:bg-bg-elevated/60"
                    >
                      {inner}
                    </a>
                  </li>
                );
              }
              return <li key={i}>{inner}</li>;
            })}
          </ul>
        </section>
      )}

      {/* ── Activity trail (was "Audit trail") ──────────────────── */}
      <section className="space-y-2">
        <div className="text-caption-1 uppercase tracking-wider text-label-secondary px-1 flex items-center gap-1">
          <HistoryIcon className="h-3.5 w-3.5" /> Activity
        </div>
        <ol className="overflow-hidden rounded-lg bg-bg-tertiary divide-y divide-separator/40">
          <li className="flex items-center gap-3 px-4 py-3">
            <Clock className="h-4 w-4 text-label-tertiary" aria-hidden="true" />
            <div className="flex-1 min-w-0">
              <div className="text-callout text-label-primary">
                Created {age}
              </div>
              <div className="text-footnote text-label-tertiary">
                {displayName(item.agent_id)}
              </div>
            </div>
          </li>
          {trail.map((e) => (
            <li
              key={e.seq}
              className="flex items-center gap-3 px-4 py-3 min-h-[44px]"
            >
              <span className="font-mono text-footnote text-label-tertiary w-8">
                #{e.seq}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-callout text-label-primary truncate">
                  {e.action}
                </div>
                <div className="text-footnote text-label-tertiary truncate">
                  {e.actor} · {new Date(e.ts).toLocaleString()}
                </div>
              </div>
              <span className="font-mono text-caption-2 text-label-tertiary">
                {shortHash(e.hash, 8)}
              </span>
            </li>
          ))}
        </ol>
      </section>

      {showRawJson && (
        <section className="space-y-2">
          <div className="text-caption-1 uppercase tracking-wider text-label-secondary px-1">
            Raw JSON (dev)
          </div>
          <JsonBlock value={item} maxHeight={360} />
        </section>
      )}
    </div>
  );
}

/* ── Why panel ─────────────────────────────────────────────────────────────
 * Collapsed by default per COPY_GUIDE §"Detail screen rewrites":
 *   - "Why we flagged this" (rationale)
 *   - "What we're proposing" (payload as label/value table — never raw JSON)
 *   - Citations are rendered separately below.
 */
function WhyPanel({ item }: { item: ApprovalItem }) {
  const [open, setOpen] = React.useState(false);
  const payloadRows = formatPayloadRows(item.proposed_action.payload);
  const hasReasoning = !!item.rationale && item.rationale.trim().length > 0;
  const hasPayload = payloadRows.length > 0;
  const hasMeta = !!item.priority || item.confidence != null;
  if (!hasReasoning && !hasPayload && !hasMeta) return null;
  return (
    <section className="rounded-xl bg-bg-elevated overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between px-4 py-3 min-h-[44px] active:bg-bg-tertiary/40 no-tap-highlight"
      >
        <span className="text-callout text-label-primary font-medium">
          Why we flagged this
        </span>
        <ChevronDown
          className={cn(
            "h-4 w-4 text-label-tertiary transition-transform",
            open && "rotate-180",
          )}
          aria-hidden="true"
        />
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-4">
          {hasReasoning && (
            <div>
              <div className="text-caption-1 uppercase tracking-wider text-label-tertiary mb-1">
                Reasoning
              </div>
              <p className="text-callout text-label-secondary leading-relaxed italic">
                {item.rationale}
              </p>
            </div>
          )}
          {hasPayload && (
            <div>
              <div className="text-caption-1 uppercase tracking-wider text-label-tertiary mb-1">
                What we’re proposing
              </div>
              <dl className="grid grid-cols-1 gap-y-1">
                {payloadRows.map(([k, v]) => (
                  <div
                    key={k}
                    className="flex items-baseline justify-between gap-3 text-callout"
                  >
                    <dt className="text-label-secondary">{k}</dt>
                    <dd className="text-label-primary text-right break-words max-w-[60%]">
                      {v}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
          {hasMeta && (
            <div>
              <div className="text-caption-1 uppercase tracking-wider text-label-tertiary mb-1">
                Details
              </div>
              <dl className="grid grid-cols-1 gap-y-1">
                <div className="flex items-baseline justify-between gap-3 text-callout">
                  <dt className="text-label-secondary">Confidence</dt>
                  <dd className="text-label-primary text-right">
                    {displayConfidence(item.confidence ?? 0, false)}
                  </dd>
                </div>
                {item.priority && (
                  <div className="flex items-baseline justify-between gap-3 text-callout">
                    <dt className="text-label-secondary">Priority</dt>
                    <dd className="text-label-primary text-right">
                      {displayPriority(item.priority)}
                    </dd>
                  </div>
                )}
                <div className="flex items-baseline justify-between gap-3 text-callout">
                  <dt className="text-label-secondary">Project</dt>
                  <dd className="text-label-primary text-right truncate">
                    {item.context.project_id}
                  </dd>
                </div>
                {item.proposed_action.target_system && (
                  <div className="flex items-baseline justify-between gap-3 text-callout">
                    <dt className="text-label-secondary">Target system</dt>
                    <dd className="text-label-primary text-right truncate">
                      {item.proposed_action.target_system}
                    </dd>
                  </div>
                )}
              </dl>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

/**
 * Flatten a payload into label/value rows for the Why panel.
 * - Object/array values are rendered as compact JSON snippets, never as
 *   pretty-printed JSON blocks (we explicitly avoid "raw JSON" per
 *   COPY_GUIDE).
 * - Keys are pretty-cased ("assignee_id" → "Assignee id").
 */
function formatPayloadRows(
  payload: Record<string, unknown> | undefined,
): Array<[string, string]> {
  if (!payload) return [];
  const rows: Array<[string, string]> = [];
  for (const [key, value] of Object.entries(payload)) {
    if (value == null) continue;
    const label = key
      .replace(/[_-]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    const labelCased = label
      ? label.charAt(0).toUpperCase() + label.slice(1).toLowerCase()
      : key;
    let display: string;
    if (typeof value === "string") {
      display = value.length > 240 ? value.slice(0, 237) + "…" : value;
    } else if (typeof value === "number" || typeof value === "boolean") {
      display = String(value);
    } else {
      try {
        const json = JSON.stringify(value);
        display = json && json.length > 240 ? json.slice(0, 237) + "…" : json;
      } catch {
        display = String(value);
      }
    }
    rows.push([labelCased, display]);
  }
  return rows;
}

function KebabMenu({
  onShowJson,
  onEscalate,
  onOpenStandalone,
}: {
  onShowJson: () => void;
  onEscalate: () => void;
  onOpenStandalone: () => void;
}) {
  const [open, setOpen] = React.useState(false);
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="More actions"
        aria-expanded={open}
        className="flex h-11 w-11 items-center justify-center text-accent active:opacity-60 no-tap-highlight"
      >
        <ArrowUpFromLine className="h-5 w-5 rotate-90" />
      </button>
      {open && (
        <>
          <button
            aria-hidden="true"
            tabIndex={-1}
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-40 cursor-default"
          />
          <div
            role="menu"
            className="absolute right-0 top-full z-50 mt-1 w-48 overflow-hidden rounded-lg bg-bg-tertiary shadow-elevated border border-separator/40"
          >
            <MenuItem
              label="Escalate"
              onClick={() => {
                setOpen(false);
                onEscalate();
              }}
            />
            <MenuItem
              label="View raw JSON"
              onClick={() => {
                setOpen(false);
                onShowJson();
              }}
            />
            <MenuItem
              label="Open in new screen"
              onClick={() => {
                setOpen(false);
                onOpenStandalone();
              }}
            />
          </div>
        </>
      )}
    </div>
  );
}

function MenuItem({
  label,
  onClick,
  destructive,
}: {
  label: string;
  onClick: () => void;
  destructive?: boolean;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={cn(
        "block w-full px-4 py-3 text-left text-body text-label-primary active:bg-bg-elevated/60 no-tap-highlight",
        destructive && "text-danger",
      )}
    >
      {label}
    </button>
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-3 animate-shimmer">
      <span className="block h-6 w-2/3 rounded bg-bg-elevated" />
      <span className="block h-4 w-5/6 rounded bg-bg-elevated" />
      <span className="block h-32 w-full rounded-xl bg-bg-elevated" />
      <span className="block h-32 w-full rounded-xl bg-bg-elevated" />
    </div>
  );
}

function humanRef(item: ApprovalItem): string {
  return item.summary ?? `${item.workflow} · ${item.approval_id.slice(0, 12)}`;
}
