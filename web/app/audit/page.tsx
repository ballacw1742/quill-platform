"use client";

import * as React from "react";
import {
  CheckCircle2,
  Cloud,
  CloudOff,
  Database,
  History as HistoryIcon,
  RotateCw,
  Search as SearchIcon,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import {
  BottomSheet,
  BottomSheetBody,
  BottomSheetTopBar,
} from "@/components/ui/sheet";
import { ListRow } from "@/components/ui/list-row";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { JsonBlock } from "@/components/approval/JsonBlock";
import {
  useAudit,
  useAuditMirrorStatus,
  useRecentAuditVerifications,
  useTriggerAuditVerify,
  useVerifyChain,
} from "@/lib/api";
import type { AuditEntry } from "@/lib/schemas";
import { cn, shortHash } from "@/lib/utils";
import { displayName, prettyCase } from "@/lib/agent-meta";
import { toast } from "sonner";

/**
 * Translate an actor token like `agent:rfi-triage` or `user:charles@quill.local`
 * into a human-readable label. Agent actors get the helper display name;
 * everything else passes through pretty-cased so we never leak raw tokens.
 */
function displayActor(actor: string | undefined | null): string {
  if (!actor) return "";
  const colon = actor.indexOf(":");
  if (colon === -1) return actor;
  const kind = actor.slice(0, colon);
  const rest = actor.slice(colon + 1);
  if (kind === "agent") return displayName(rest);
  if (kind === "user" || kind === "owner" || kind === "partner") return rest;
  if (kind === "system") return "System";
  return actor;
}

/**
 * Translate event_type strings (e.g. `approval.created`) to plain English.
 */
function displayEvent(action: string | undefined | null): string {
  if (!action) return "Event";
  switch (action) {
    case "approval.created":
      return "Item created";
    case "approval.approved":
      return "Approved";
    case "approval.rejected":
      return "Sent back";
    case "approval.escalated":
      return "Escalated";
    case "approval.executed":
      return "Executed";
    case "approval.expired":
      return "Expired";
    case "agent.trust_tier_changed":
      return "Trust level changed";
    case "audit.genesis":
      return "Activity log started";
    case "audit.verify":
      return "Activity log verified";
    default:
      return prettyCase(action.replace(/\./g, " "));
  }
}

/**
 * /audit — iOS-redesign chain log + verifier.
 *
 * MOBILE_UX_SPEC.md §"Tab 3 — Audit":
 *   - Top hero: chain integrity (green dot / red dot), last verified, total
 *     entries, "Verify now" button, mirror status row.
 *   - List of audit entries as ListRow items, icon mapped per event_type.
 *   - Tap → expand sheet with full payload + chain context.
 *   - Verify result lands in a sheet.
 */

const EVENT_TONE: Record<string, "success" | "danger" | "warning" | "info" | "neutral"> = {
  "approval.created": "info",
  "approval.approved": "success",
  "approval.rejected": "danger",
  "approval.escalated": "warning",
  "approval.executed": "success",
  "approval.expired": "neutral",
  "agent.trust_tier_changed": "warning",
  "audit.genesis": "neutral",
};

function eventTone(action: string): "success" | "danger" | "warning" | "info" | "neutral" {
  return EVENT_TONE[action] ?? "neutral";
}

function eventIcon(action: string) {
  if (action.includes("approved") || action.includes("executed"))
    return <CheckCircle2 className="h-4 w-4" />;
  if (action.includes("rejected"))
    return <ShieldAlert className="h-4 w-4" />;
  if (action.includes("verify"))
    return <ShieldCheck className="h-4 w-4" />;
  return <HistoryIcon className="h-4 w-4" />;
}

export default function AuditPage() {
  const { data, isLoading } = useAudit();
  const entries = (data ?? []) as AuditEntry[];

  const verify = useVerifyChain();
  const triggerVerify = useTriggerAuditVerify();
  const { data: mirrorStatus } = useAuditMirrorStatus();
  const { data: recentVerifications } = useRecentAuditVerifications(5);

  const [search, setSearch] = React.useState("");
  const [searchOpen, setSearchOpen] = React.useState(false);
  const [openEntry, setOpenEntry] = React.useState<AuditEntry | null>(null);
  const [verifyResultOpen, setVerifyResultOpen] = React.useState(false);

  const filtered = React.useMemo(
    () =>
      search.trim()
        ? entries.filter((e) => {
            const blob =
              `${e.action} ${e.actor} ${e.approval_id ?? ""} ${e.hash} ${e.notes ?? ""}`.toLowerCase();
            return blob.includes(search.toLowerCase());
          })
        : entries,
    [entries, search],
  );

  const onVerify = async () => {
    try {
      await verify.mutateAsync();
      setVerifyResultOpen(true);
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : "Verification failed",
      );
    }
  };

  const lastVerifyResult = recentVerifications?.[0];
  const chainOk = lastVerifyResult ? lastVerifyResult.result === "ok" : true;

  return (
    <MobileShell>
      <TopBar
        title="Activity"
        right={
          <button
            type="button"
            aria-label={searchOpen ? "Close search" : "Search"}
            onClick={() => {
              setSearchOpen((v) => {
                if (v) setSearch("");
                return !v;
              });
            }}
            className="flex h-11 w-11 items-center justify-center text-accent active:opacity-60 no-tap-highlight"
          >
            <SearchIcon className="h-5 w-5" />
          </button>
        }
      />

      <div className="bg-bg-elevated min-h-full">
        {/* Hero — chain integrity */}
        <div className="px-4 pt-4">
          <ChainIntegrityCard
            ok={chainOk}
            entries={entries.length}
            mirrorStatus={mirrorStatus}
            verifyPending={verify.isPending || triggerVerify.isPending}
            onVerify={onVerify}
          />
        </div>

        {/* Search bar */}
        {searchOpen && (
          <div className="px-4 pt-3 pb-2">
            <Input
              autoFocus
              placeholder="Search by hash, actor, approval id…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-11 rounded-md bg-bg-tertiary border-transparent text-body"
            />
          </div>
        )}

        {/* Section header */}
        <div className="px-4 pt-5 pb-2 flex items-center justify-between">
          <h2 className="text-caption-1 uppercase tracking-wider text-label-secondary">
            Recent entries
          </h2>
          <span className="text-footnote text-label-tertiary">
            {filtered.length} shown
          </span>
        </div>

        {isLoading ? (
          <SkeletonRows />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<HistoryIcon />}
            title={search ? "No matches" : "No activity yet"}
            subtitle={
              search
                ? "Try a different search."
                : "Every action Quill takes will be recorded here."
            }
          />
        ) : (
          <ul className="divide-y divide-separator/40 bg-bg-tertiary mx-4 rounded-lg overflow-hidden">
            {filtered.slice(0, 200).map((e) => {
              const human = displayActor(e.actor);
              return (
                <li key={e.seq}>
                  <ListRow
                    icon={eventIcon(e.action)}
                    iconTone={eventTone(e.action)}
                    title={displayEvent(e.action)}
                    subtitle={
                      e.approval_id
                        ? `${human} · ${shortHash(e.approval_id, 14)}…`
                        : human
                    }
                    chip={shortHash(e.hash, 8)}
                    onClick={() => setOpenEntry(e)}
                    hideDivider
                  />
                </li>
              );
            })}
          </ul>
        )}
        <div className="h-8" />
      </div>

      {/* Entry detail sheet */}
      <BottomSheet
        open={!!openEntry}
        onOpenChange={(v) => !v && setOpenEntry(null)}
        ariaLabel="Activity entry"
        fullHeight
      >
        <BottomSheetTopBar
          title={openEntry ? displayEvent(openEntry.action) : "Entry"}
          left={
            <button
              type="button"
              onClick={() => setOpenEntry(null)}
              className="text-body text-accent active:opacity-60 no-tap-highlight min-h-[44px] -ml-2 px-2"
            >
              Done
            </button>
          }
        />
        <BottomSheetBody>
          {openEntry && <EntryDetail entry={openEntry} />}
        </BottomSheetBody>
      </BottomSheet>

      {/* Verify result sheet */}
      <BottomSheet
        open={verifyResultOpen}
        onOpenChange={setVerifyResultOpen}
        ariaLabel="Chain verification result"
      >
        <BottomSheetTopBar
          title="Chain verification"
          left={
            <button
              type="button"
              onClick={() => setVerifyResultOpen(false)}
              className="text-body text-accent active:opacity-60 no-tap-highlight min-h-[44px] -ml-2 px-2"
            >
              Done
            </button>
          }
        />
        <BottomSheetBody>
          {verify.data && (
            <div className="flex flex-col items-center gap-3 py-6 text-center">
              <div
                className={cn(
                  "flex h-20 w-20 items-center justify-center rounded-full",
                  verify.data.ok
                    ? "bg-success/10 text-success"
                    : "bg-danger/10 text-danger",
                )}
              >
                {verify.data.ok ? (
                  <ShieldCheck className="h-10 w-10" />
                ) : (
                  <ShieldAlert className="h-10 w-10" />
                )}
              </div>
              <div>
                <div className="text-title-2 text-label-primary">
                  {verify.data.ok ? "Chain verified" : "Drift detected"}
                </div>
                <div className="text-body text-label-secondary mt-1">
                  Verified {verify.data.verified} / {verify.data.total} entries
                </div>
              </div>
              {verify.data.last_hash && (
                <div className="font-mono text-footnote text-label-tertiary break-all max-w-xs">
                  last hash · {verify.data.last_hash}
                </div>
              )}
              {!verify.data.ok &&
                verify.data.failures &&
                verify.data.failures.length > 0 && (
                  <div className="w-full rounded-lg bg-bg-elevated p-3 text-left">
                    <div className="text-caption-1 uppercase tracking-wider text-label-secondary mb-1">
                      Failures
                    </div>
                    <JsonBlock value={verify.data.failures} maxHeight={200} />
                  </div>
                )}
            </div>
          )}
        </BottomSheetBody>
      </BottomSheet>
    </MobileShell>
  );
}

/* ── Chain integrity hero ────────────────────────────────────────────── */

function ChainIntegrityCard({
  ok,
  entries,
  mirrorStatus,
  verifyPending,
  onVerify,
}: {
  ok: boolean;
  entries: number;
  mirrorStatus:
    | {
        mode: "b2" | "local";
        bucket: string | null;
        lag_seconds: number | null;
        queue_depth: number;
        last_mirrored_at: string | null;
      }
    | undefined;
  verifyPending: boolean;
  onVerify: () => void;
}) {
  const isLocal = mirrorStatus?.mode === "local";
  return (
    <section className="overflow-hidden rounded-xl bg-bg-tertiary shadow-card">
      <div className="flex items-start gap-3 p-4">
        <div
          className={cn(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-full",
            ok ? "bg-success/10 text-success" : "bg-danger/10 text-danger",
          )}
          aria-hidden="true"
        >
          {ok ? (
            <ShieldCheck className="h-6 w-6" />
          ) : (
            <ShieldAlert className="h-6 w-6" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-title-3 text-label-primary">
            {ok ? "Chain verified" : "Drift detected"}
          </div>
          <div className="text-callout text-label-secondary">
            {entries.toLocaleString()} entries
          </div>
        </div>
        <button
          type="button"
          onClick={onVerify}
          disabled={verifyPending}
          className="flex items-center gap-1 rounded-md bg-accent/10 px-3 py-2 text-callout font-medium text-accent active:opacity-60 disabled:opacity-50 no-tap-highlight"
        >
          <RotateCw
            className={cn("h-4 w-4", verifyPending && "animate-spin")}
          />
          Verify now
        </button>
      </div>
      <div className="border-t border-separator/40 px-4 py-3 flex items-center gap-3">
        {isLocal ? (
          <Database className="h-4 w-4 text-warning" />
        ) : (
          <Cloud className="h-4 w-4 text-success" />
        )}
        <div className="flex-1 min-w-0">
          <div className="text-callout text-label-primary">
            {isLocal
              ? "Offsite mirror — local mode"
              : `Offsite mirror — b2://${mirrorStatus?.bucket ?? "quill-audit"}`}
          </div>
          <div className="text-footnote text-label-tertiary">
            {mirrorStatus?.lag_seconds != null
              ? `${formatLag(mirrorStatus.lag_seconds)} · queue ${mirrorStatus.queue_depth}`
              : "Mirror status pending"}
          </div>
        </div>
        {!isLocal && <CloudOff className="hidden" />}
      </div>
    </section>
  );
}

function formatLag(s: number) {
  if (s < 60) return `${Math.round(s)}s behind`;
  if (s < 3600) return `${(s / 60).toFixed(1)}m behind`;
  return `${(s / 3600).toFixed(1)}h behind`;
}

/* ── Entry detail content ────────────────────────────────────────────── */

function EntryDetail({ entry }: { entry: AuditEntry }) {
  return (
    <div className="space-y-5">
      <section className="rounded-xl bg-bg-elevated p-4 space-y-2">
        <div className="text-caption-1 uppercase tracking-wider text-label-secondary">
          Event
        </div>
        <dl className="grid grid-cols-1 gap-y-1">
          <Row k="Type" v={displayEvent(entry.action)} />
          <Row k="Actor" v={displayActor(entry.actor)} />
          <Row
            k="Time"
            v={entry.ts ? new Date(entry.ts).toLocaleString() : "—"}
          />
          <Row k="Sequence" v={`#${entry.seq}`} />
          {entry.approval_id && (
            <Row k="Approval" v={entry.approval_id} mono />
          )}
        </dl>
      </section>

      <section className="rounded-xl bg-bg-elevated p-4 space-y-2">
        <div className="text-caption-1 uppercase tracking-wider text-label-secondary">
          Hash chain
        </div>
        <dl className="grid grid-cols-1 gap-y-1">
          <Row k="Hash" v={entry.hash} mono />
          {entry.prev_hash && <Row k="Prev hash" v={entry.prev_hash} mono />}
          {entry.payload_hash && (
            <Row k="Payload hash" v={entry.payload_hash} mono />
          )}
        </dl>
      </section>

      {(entry as { payload?: unknown }).payload != null && (
        <section className="space-y-2">
          <div className="px-1 text-caption-1 uppercase tracking-wider text-label-secondary">
            Payload
          </div>
          <JsonBlock value={(entry as { payload?: unknown }).payload} maxHeight={360} />
        </section>
      )}

      {entry.notes && (
        <section className="rounded-xl bg-bg-elevated p-4">
          <div className="text-caption-1 uppercase tracking-wider text-label-secondary mb-1">
            Notes
          </div>
          <div className="text-callout text-label-primary">{entry.notes}</div>
        </section>
      )}
    </div>
  );
}

function Row({ k, v, mono = false }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-callout">
      <dt className="text-label-secondary shrink-0">{k}</dt>
      <dd
        className={cn(
          "text-right text-label-primary truncate",
          mono && "font-mono text-footnote",
        )}
      >
        {v}
      </dd>
    </div>
  );
}

function SkeletonRows() {
  return (
    <ul className="bg-bg-tertiary mx-4 mt-2 rounded-lg overflow-hidden divide-y divide-separator/40">
      {Array.from({ length: 5 }).map((_, i) => (
        <li
          key={i}
          className="flex items-center gap-3 px-4 py-3 animate-shimmer min-h-[56px]"
        >
          <span className="h-7 w-7 rounded-md bg-bg-elevated" />
          <div className="flex-1 space-y-1.5">
            <span className="block h-3.5 w-2/3 rounded-sm bg-bg-elevated" />
            <span className="block h-3 w-1/2 rounded-sm bg-bg-elevated" />
          </div>
        </li>
      ))}
    </ul>
  );
}
