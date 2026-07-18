"use client";

/**
 * /pipeline/deals/[id] — Deal Detail (Lovable redesign port)
 *
 * Lovable source: quill-platform-builder/src/routes/pipeline.deals.$id.tsx
 * Visual layer ported 1:1; real-data wiring kept from prod (lib/api.ts).
 * Token changes: text-green-400 -> text-success; text-red-400 -> text-danger;
 *   text-blue-400 -> text-info; text-purple-400 -> text-accent;
 *   text-warning -> text-warning; bg-[stage]/10 badge patterns match Lovable.
 * Envelope adapters: useDealActivities -> {items}, useDeal -> DealWithAccount.
 */

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  Calendar,
  ChevronRight,
  FileText,
  Handshake,
  Mail,
  MessageSquare,
  Phone,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import {
  useDeal,
  useUpdateDeal,
  useUpdateAccount,
  useDealActivities,
  useAddDealActivity,
} from "@/lib/api";
import type { DealWithAccount, DealActivity } from "@/lib/schemas";
import { ACTIVITY_TYPES, WORKLOAD_TYPES } from "@/lib/schemas";

// ── Stage config ──────────────────────────────────────────────────────────────

const STAGE_ORDER_ACTIVE = [
  "prospect",
  "qualified",
  "proposal",
  "negotiating",
  "won",
] as const;

// ── Helpers ───────────────────────────────────────────────────────────────────

function stageBadgeCls(stage: string): string {
  switch (stage) {
    case "prospect":    return "text-label-secondary bg-fill-quaternary";
    case "qualified":   return "text-info bg-info/10";
    case "proposal":    return "text-accent bg-accent/10";
    case "negotiating": return "text-warning bg-warning/10";
    case "won":         return "text-success bg-success/10";
    case "lost":        return "text-danger bg-danger/10";
    default:            return "text-label-secondary bg-fill-quaternary";
  }
}

function formatValue(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
  return `$${v}`;
}

function timeAgo(dateStr: string): string {
  const d = new Date(dateStr);
  const sec = Math.floor((Date.now() - d.getTime()) / 1000);
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// ── Activity icons ────────────────────────────────────────────────────────────

function ActivityIcon({ type }: { type: string }) {
  const cls = "h-4 w-4 shrink-0";
  switch (type) {
    case "call":          return <Phone className={cn(cls, "text-success")} />;
    case "email":         return <Mail className={cn(cls, "text-info")} />;
    case "meeting":       return <Calendar className={cn(cls, "text-accent")} />;
    case "proposal_sent": return <FileText className={cn(cls, "text-warning")} />;
    case "contract_sent": return <Handshake className={cn(cls, "text-warning")} />;
    default:              return <MessageSquare className={cn(cls, "text-label-tertiary")} />;
  }
}

function activityLabel(type: string): string {
  const labels: Record<string, string> = {
    call: "Call",
    email: "Email",
    meeting: "Meeting",
    proposal_sent: "Proposal Sent",
    contract_sent: "Contract Sent",
    note: "Note",
  };
  return labels[type] ?? type;
}

// ── Shared form helpers ───────────────────────────────────────────────────────

const inputCls =
  "w-full rounded-xl bg-bg-elevated shadow-card px-3 py-2.5 text-body text-label-primary placeholder:text-label-tertiary focus:outline-none focus:border-accent";

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-caption-1 text-label-secondary">{label}</span>
      {children}
    </label>
  );
}

// ── Stage Stepper ─────────────────────────────────────────────────────────────

function StageStepper({
  currentStage,
  onAdvance,
  onMarkLost,
  isPending,
}: {
  currentStage: string;
  onAdvance: (stage: string) => void;
  onMarkLost: () => void;
  isPending: boolean;
}) {
  const currentIdx = STAGE_ORDER_ACTIVE.indexOf(
    currentStage as (typeof STAGE_ORDER_ACTIVE)[number],
  );
  const isTerminal = currentStage === "won" || currentStage === "lost";

  return (
    <div>
      <div className="flex items-center gap-1 mb-3">
        {STAGE_ORDER_ACTIVE.map((stage, idx) => {
          const isCurrent = idx === currentIdx;
          const isPast = currentIdx > -1 && idx < currentIdx;
          const isFuture = currentIdx === -1 || idx > currentIdx;
          return (
            <React.Fragment key={stage}>
              <button
                type="button"
                disabled={isPending || isTerminal || idx <= currentIdx}
                onClick={() =>
                  !isTerminal && idx > currentIdx && onAdvance(stage)
                }
                className={cn(
                  "flex-1 py-1.5 rounded-full text-caption-2 font-semibold transition-all",
                  isCurrent && "bg-accent text-primary-foreground",
                  isPast && "bg-accent/30 text-accent",
                  isFuture &&
                    !isTerminal &&
                    "bg-fill-quaternary text-label-tertiary hover:bg-separator/30",
                  isTerminal &&
                    "bg-fill-quaternary text-label-quaternary cursor-default",
                )}
              >
                {stage.charAt(0).toUpperCase() + stage.slice(1)}
              </button>
              {idx < STAGE_ORDER_ACTIVE.length - 1 && (
                <ChevronRight className="h-3 w-3 text-label-quaternary shrink-0" />
              )}
            </React.Fragment>
          );
        })}
      </div>
      {!isTerminal && (
        <button
          type="button"
          disabled={isPending}
          onClick={onMarkLost}
          className="text-caption-1 font-semibold text-danger bg-danger/10 rounded-xl px-3 py-1.5 disabled:opacity-50"
        >
          Mark Lost
        </button>
      )}
      {currentStage === "lost" && (
        <span className="text-caption-1 text-danger font-semibold">Deal Lost</span>
      )}
      {currentStage === "won" && (
        <span className="text-caption-1 text-success font-semibold">Deal Won</span>
      )}
    </div>
  );
}

// ── Log Activity Modal ────────────────────────────────────────────────────────

function LogActivityModal({
  dealId,
  onClose,
}: {
  dealId: string;
  onClose: () => void;
}) {
  const addActivity = useAddDealActivity(dealId);
  const [type, setType] = React.useState("call");
  const [summary, setSummary] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!summary.trim()) {
      setError("Summary is required.");
      return;
    }
    try {
      await addActivity.mutateAsync({
        activity_type: type,
        summary: summary.trim(),
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to log activity");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 backdrop-blur-sm sm:items-center">
      <div className="w-full max-w-lg rounded-t-2xl sm:rounded-2xl bg-chrome border border-hairline shadow-2xl pb-safe">
        <div className="flex items-center justify-between px-4 pt-4 pb-2 border-b border-hairline">
          <h2 className="text-headline font-semibold text-label-primary">
            Log Activity
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-label-secondary active:text-label-primary"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3 px-4 py-4">
          {error && (
            <p className="text-caption-1 text-danger bg-danger/10 rounded-xl px-3 py-2">
              {error}
            </p>
          )}
          <Field label="Type">
            <select
              className={inputCls}
              value={type}
              onChange={(e) => setType(e.target.value)}
            >
              {ACTIVITY_TYPES.map((t) => (
                <option key={t} value={t}>
                  {activityLabel(t)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Summary *">
            <textarea
              rows={4}
              className={cn(inputCls, "resize-none")}
              placeholder="What happened?"
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              required
            />
          </Field>
          <button
            type="submit"
            disabled={addActivity.isPending}
            className={cn(
              "mt-2 w-full rounded-xl py-3 text-body font-semibold bg-accent text-primary-foreground",
              addActivity.isPending && "opacity-40 cursor-not-allowed",
            )}
          >
            {addActivity.isPending ? "Logging..." : "Log Activity"}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── Activity Tab ──────────────────────────────────────────────────────────────

function ActivityTab({ dealId }: { dealId: string }) {
  // Envelope adapter: useDealActivities -> DealActivityListPage {items, total}
  const { data: activitiesData, isLoading } = useDealActivities(dealId);
  const activities = activitiesData?.items ?? [];
  const [showLog, setShowLog] = React.useState(false);

  return (
    <div>
      <button
        type="button"
        onClick={() => setShowLog(true)}
        className="w-full mb-4 bg-accent/10 text-accent font-semibold text-callout rounded-2xl py-3 border border-accent/30 hover:bg-accent/20"
      >
        + Log Activity
      </button>

      {isLoading && (
        <p className="text-caption-1 text-label-tertiary text-center py-6">
          Loading...
        </p>
      )}

      {!isLoading && activities.length === 0 && (
        <p className="text-caption-1 text-label-tertiary text-center py-8">
          No activities yet. Log your first touchpoint above.
        </p>
      )}

      <div className="space-y-3">
        {activities.map((a: DealActivity) => (
          <div
            key={a.id}
            className="rounded-2xl bg-chrome/80 border border-hairline p-3"
          >
            <div className="flex items-start gap-3">
              <div className="mt-0.5">
                <ActivityIcon type={a.activity_type} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-caption-1 font-semibold text-label-secondary">
                    {activityLabel(a.activity_type)}
                  </span>
                  <span className="text-caption-2 text-label-tertiary">
                    {timeAgo(a.created_at)}
                  </span>
                </div>
                <p className="text-callout text-label-primary">{a.summary}</p>
                {a.created_by && (
                  <p className="text-caption-2 text-label-tertiary mt-1">
                    {a.created_by}
                  </p>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {showLog && (
        <LogActivityModal dealId={dealId} onClose={() => setShowLog(false)} />
      )}
    </div>
  );
}

// ── Details Tab ───────────────────────────────────────────────────────────────

function DetailsTab({ deal }: { deal: DealWithAccount }) {
  const updateDeal = useUpdateDeal(deal.id);
  const updateAccount = useUpdateAccount(deal.account_id);

  const [contactName, setContactName] = React.useState(
    deal.account.primary_contact_name ?? "",
  );
  const [contactEmail, setContactEmail] = React.useState(
    deal.account.primary_contact_email ?? "",
  );
  const [contactPhone, setContactPhone] = React.useState(
    deal.account.primary_contact_phone ?? "",
  );
  const [industry, setIndustry] = React.useState(deal.account.industry ?? "");
  const [website, setWebsite] = React.useState(deal.account.website ?? "");

  const [workloadType, setWorkloadType] = React.useState(deal.workload_type ?? "");
  const [mwRequired, setMwRequired] = React.useState(
    deal.mw_required?.toString() ?? "",
  );
  const [valueUsd, setValueUsd] = React.useState(deal.value_usd?.toString() ?? "");
  const [probabilityPct, setProbabilityPct] = React.useState(
    deal.probability_pct?.toString() ?? "",
  );
  const [expectedClose, setExpectedClose] = React.useState(deal.expected_close ?? "");
  const [notes, setNotes] = React.useState(deal.notes ?? "");
  const [campusId, setCampusId] = React.useState(deal.campus_id ?? "");
  const [lostReason, setLostReason] = React.useState(deal.lost_reason ?? "");

  const [saved, setSaved] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(false);
    try {
      await updateAccount.mutateAsync({
        primary_contact_name: contactName || null,
        primary_contact_email: contactEmail || null,
        primary_contact_phone: contactPhone || null,
        industry: industry || null,
        website: website || null,
      });
      await updateDeal.mutateAsync({
        workload_type: workloadType || null,
        mw_required: mwRequired ? parseFloat(mwRequired) : null,
        value_usd: valueUsd ? parseFloat(valueUsd) : null,
        probability_pct: probabilityPct ? parseInt(probabilityPct, 10) : null,
        expected_close: expectedClose || null,
        notes: notes || null,
        campus_id: campusId || null,
        lost_reason: lostReason || null,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    }
  }

  const isPending = updateDeal.isPending || updateAccount.isPending;

  return (
    <form onSubmit={handleSave} className="flex flex-col gap-3">
      {error && (
        <p className="text-caption-1 text-danger bg-danger/10 rounded-xl px-3 py-2">
          {error}
        </p>
      )}

      <p className="text-footnote font-bold text-label-tertiary uppercase tracking-wide">
        Account
      </p>
      <Field label="Contact Name">
        <input
          className={inputCls}
          value={contactName}
          onChange={(e) => setContactName(e.target.value)}
        />
      </Field>
      <Field label="Contact Email">
        <input
          type="email"
          className={inputCls}
          value={contactEmail}
          onChange={(e) => setContactEmail(e.target.value)}
        />
      </Field>
      <Field label="Contact Phone">
        <input
          className={inputCls}
          value={contactPhone}
          onChange={(e) => setContactPhone(e.target.value)}
        />
      </Field>
      <Field label="Industry">
        <input
          className={inputCls}
          value={industry}
          onChange={(e) => setIndustry(e.target.value)}
        />
      </Field>
      <Field label="Website">
        <input
          className={inputCls}
          value={website}
          onChange={(e) => setWebsite(e.target.value)}
        />
      </Field>

      <p className="text-footnote font-bold text-label-tertiary uppercase tracking-wide mt-3">
        Deal
      </p>
      <Field label="Workload Type">
        <select
          className={inputCls}
          value={workloadType}
          onChange={(e) => setWorkloadType(e.target.value)}
        >
          <option value="">Select...</option>
          {WORKLOAD_TYPES.map((w) => (
            <option key={w} value={w}>
              {w}
            </option>
          ))}
        </select>
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="MW Required">
          <input
            type="number"
            className={inputCls}
            value={mwRequired}
            onChange={(e) => setMwRequired(e.target.value)}
          />
        </Field>
        <Field label="Annual Value (USD)">
          <input
            type="number"
            className={inputCls}
            value={valueUsd}
            onChange={(e) => setValueUsd(e.target.value)}
          />
        </Field>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Probability %">
          <input
            type="number"
            min="0"
            max="100"
            className={inputCls}
            value={probabilityPct}
            onChange={(e) => setProbabilityPct(e.target.value)}
          />
        </Field>
        <Field label="Expected Close">
          <input
            type="date"
            className={inputCls}
            value={expectedClose}
            onChange={(e) => setExpectedClose(e.target.value)}
          />
        </Field>
      </div>
      <Field label="Notes">
        <textarea
          rows={3}
          className={cn(inputCls, "resize-none")}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </Field>

      {deal.stage === "won" && (
        <Field label="Linked Campus ID">
          <input
            className={cn(inputCls, "font-mono text-caption-1")}
            value={campusId}
            onChange={(e) => setCampusId(e.target.value)}
          />
        </Field>
      )}
      {deal.stage === "lost" && (
        <Field label="Lost Reason">
          <textarea
            rows={2}
            className={cn(inputCls, "resize-none")}
            value={lostReason}
            onChange={(e) => setLostReason(e.target.value)}
          />
        </Field>
      )}

      <button
        type="submit"
        disabled={isPending}
        className={cn(
          "mt-2 w-full rounded-xl py-3 text-body font-semibold bg-accent text-primary-foreground",
          isPending && "opacity-40 cursor-not-allowed",
        )}
      >
        {isPending ? "Saving..." : saved ? "Saved" : "Save Changes"}
      </button>
    </form>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function DealDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const dealId = Array.isArray(params.id) ? params.id[0] : (params.id ?? "");

  // useDeal -> DealWithAccount | undefined (no envelope — single item)
  const { data: deal, error, isLoading } = useDeal(dealId);
  const updateDeal = useUpdateDeal(dealId);

  const [tab, setTab] = React.useState<"activity" | "details">("activity");

  async function handleAdvance(newStage: string) {
    await updateDeal.mutateAsync({ stage: newStage });
  }

  async function handleMarkLost() {
    await updateDeal.mutateAsync({ stage: "lost" });
  }

  return (
    <MobileShell>
      <TopBar
        title={deal?.name ?? "Deal"}
        left={
          <button
            type="button"
            aria-label="Back to pipeline"
            onClick={() => router.push("/pipeline")}
            className="flex items-center gap-1 text-callout font-semibold text-accent"
          >
            <ArrowLeft className="h-4 w-4" />
            Back
          </button>
        }
      />

      <div className="mx-auto w-full max-w-[708px] px-4 pt-3 pb-16 md:px-8 flex flex-col gap-4">
        {error && (
          <div className="rounded-2xl bg-danger/10 border border-danger/20 px-4 py-3 text-caption-1 text-danger">
            Failed to load deal.
          </div>
        )}
        {isLoading && (
          <p className="text-callout text-label-tertiary text-center py-12">
            Loading...
          </p>
        )}
        {deal && (
          <>
            <div className="border-b border-hairline pb-4">
              <p className="text-title-2 font-bold text-label-primary mb-1">
                {deal.account.name}
              </p>
              <div className="flex items-center flex-wrap gap-2">
                <span
                  className={cn(
                    "text-caption-1 font-semibold rounded-full px-2.5 py-1",
                    stageBadgeCls(deal.stage),
                  )}
                >
                  {deal.stage.charAt(0).toUpperCase() + deal.stage.slice(1)}
                </span>
                {deal.value_usd != null && (
                  <span className="text-caption-1 text-label-secondary font-medium">
                    {formatValue(deal.value_usd)}
                  </span>
                )}
                {deal.mw_required != null && (
                  <span className="text-caption-1 text-accent font-semibold">
                    {deal.mw_required} MW
                  </span>
                )}
                {deal.probability_pct != null && (
                  <span className="text-caption-1 text-label-secondary">
                    {deal.probability_pct}% prob.
                  </span>
                )}
                {deal.expected_close && (
                  <span
                    className={cn(
                      "text-caption-1",
                      new Date(deal.expected_close) < new Date()
                        ? "text-danger font-semibold"
                        : "text-label-tertiary",
                    )}
                  >
                    Close: {deal.expected_close}
                  </span>
                )}
              </div>
            </div>

            <StageStepper
              currentStage={deal.stage}
              onAdvance={handleAdvance}
              onMarkLost={handleMarkLost}
              isPending={updateDeal.isPending}
            />

            <div className="flex border-b border-hairline gap-6">
              {(["activity", "details"] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTab(t)}
                  className={cn(
                    "pb-2 text-callout font-semibold transition-colors capitalize",
                    tab === t
                      ? "text-accent border-b-2 border-accent -mb-px"
                      : "text-label-tertiary",
                  )}
                >
                  {t}
                </button>
              ))}
            </div>

            {tab === "activity" ? (
              <ActivityTab dealId={dealId} />
            ) : (
              <DetailsTab deal={deal} />
            )}
          </>
        )}
      </div>
    </MobileShell>
  );
}
