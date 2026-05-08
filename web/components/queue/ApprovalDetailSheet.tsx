"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  ArrowUpFromLine,
  Brain,
  Check,
  Clock,
  ExternalLink,
  Pencil,
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
import { useApproval, useAudit, useDecide } from "@/lib/api";
import type { ApprovalItem } from "@/lib/schemas";
import type { ActionIntent } from "@/lib/auth";
import { formatDistanceToNowStrict } from "date-fns";
import { toast } from "sonner";
import { cn, shortHash } from "@/lib/utils";
import { AgentBadge } from "./AgentBadge";
import { FlagChips } from "./FlagChips";
import { LANE_META } from "./laneMeta";

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
  const startEdit = () => setEditOpen(true);
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
      toast.error("Reason required for rejection.");
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
      await decide.mutateAsync({
        id: item.approval_id,
        decision: wire,
        reason:
          wire === "approved" ? undefined : reason || undefined,
        edited_payload: editedPayload ?? undefined,
        passkey_assertion: assertion?.auth_assertion,
      });
      toast.success(
        `${wire === "approved" ? "Approved" : wire === "rejected" ? "Rejected" : "Escalated"} ${item.approval_id.slice(0, 16)}…`,
      );
      onClose();
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : "Decision failed — try again.",
      );
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
          title={item ? "Approval" : isLoading ? "Loading…" : "Not found"}
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
              Couldn’t load this approval.
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
                {reasonOpen === "reject" ? "Why reject?" : "Why escalate?"}
              </div>
              <textarea
                className="w-full min-h-[88px] rounded-md border border-separator-opaque bg-bg-tertiary px-3 py-2 text-body text-label-primary"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder={
                  reasonOpen === "reject"
                    ? "Required — what's wrong?"
                    : "Optional — context for the dual approver."
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
              <X className="h-4 w-4" /> Reject
            </Button>
            <Button
              variant="secondary"
              onClick={startEdit}
              className="h-[50px] flex-1 rounded-lg text-headline"
              disabled={decide.isPending}
            >
              <Pencil className="h-4 w-4" /> Edit
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
              ? "Confirm rejection"
              : pendingMode === "escalate"
                ? "Confirm escalation"
                : "Confirm"
        }
        description={
          item
            ? pendingMode === "approve" || pendingMode === "edit-then-approve"
              ? item.proposed_action.target_system
                ? `This will execute against ${item.proposed_action.target_system} on confirmation.`
                : "This marks the action approved (no external write)."
              : pendingMode === "reject"
                ? `Reject ${humanRef(item)}.`
                : `Escalate ${humanRef(item)} to dual-approver.`
            : "Confirm with passkey."
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
  const summary =
    item.summary ??
    item.rationale ??
    `${item.proposed_action.kind} → ${item.proposed_action.target_system ?? "draft-only"}`;
  const lane = LANE_META[item.lane];
  const age = formatDistanceToNowStrict(new Date(item.created_at), {
    addSuffix: true,
  });
  const triageFields: Array<[string, string | undefined]> = [
    ["Workflow", item.workflow],
    ["Lane", lane?.short],
    ["Agent", `${item.agent_id} @ ${item.agent_version}`],
    ["Confidence", `${Math.round((item.confidence ?? 0) * 100)}%`],
    ["Target", item.proposed_action.target_system ?? "draft-only"],
    ["Project", item.context.project_id],
  ];

  return (
    <div className="space-y-5">
      {/* Hero card — agent's headline recommendation */}
      <section className="space-y-3">
        <div className="flex items-start gap-3">
          <AgentBadge agentId={item.agent_id} className="h-9 w-9" />
          <div className="min-w-0 flex-1">
            <div className="text-title-3 text-label-primary leading-tight">
              {summary}
            </div>
            <div className="mt-1 text-footnote text-label-tertiary">
              {item.approval_id}
            </div>
          </div>
        </div>
        <FlagChips item={item} />
      </section>

      {/* Triage classification */}
      <section className="rounded-xl bg-bg-elevated p-4 space-y-2">
        <div className="text-caption-1 uppercase tracking-wider text-label-secondary">
          Triage classification
        </div>
        <dl className="grid grid-cols-1 gap-y-1">
          {triageFields.map(([k, v]) =>
            v ? (
              <div
                key={k}
                className="flex items-baseline justify-between gap-3 text-callout"
              >
                <dt className="text-label-secondary">{k}</dt>
                <dd className="text-label-primary text-right truncate">{v}</dd>
              </div>
            ) : null,
          )}
        </dl>
      </section>

      {/* Context: source artifacts */}
      {item.context.sources.length > 0 && (
        <section className="space-y-2">
          <div className="text-caption-1 uppercase tracking-wider text-label-secondary px-1">
            Context · sources
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

      {/* Reasoning */}
      {item.rationale && (
        <section className="space-y-2">
          <div className="text-caption-1 uppercase tracking-wider text-label-secondary px-1 flex items-center gap-1">
            <Brain className="h-3.5 w-3.5" /> Agent reasoning
          </div>
          <p className="rounded-lg bg-bg-elevated p-3 text-callout text-label-secondary italic leading-relaxed">
            {item.rationale}
          </p>
        </section>
      )}

      {/* Audit trail */}
      <section className="space-y-2">
        <div className="text-caption-1 uppercase tracking-wider text-label-secondary px-1 flex items-center gap-1">
          <HistoryIcon className="h-3.5 w-3.5" /> Audit trail
        </div>
        <ol className="overflow-hidden rounded-lg bg-bg-tertiary divide-y divide-separator/40">
          <li className="flex items-center gap-3 px-4 py-3">
            <Clock className="h-4 w-4 text-label-tertiary" aria-hidden="true" />
            <div className="flex-1 min-w-0">
              <div className="text-callout text-label-primary">
                Created {age}
              </div>
              <div className="text-footnote text-label-tertiary">
                {item.agent_id}
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
            Raw JSON
          </div>
          <JsonBlock value={item} maxHeight={360} />
        </section>
      )}
    </div>
  );
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
