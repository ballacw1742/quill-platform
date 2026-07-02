"use client";

/**
 * /pipeline/deals/[id] — Deal Detail Page (Sprint 1B)
 *
 * Tabs: Activity log | Deal & account details (editable)
 * Stage stepper for advancing through pipeline.
 * Design: dark Quill theme, iOS-style cards, accent blue #0A84FF.
 */

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  Phone,
  Mail,
  MessageSquare,
  Calendar,
  FileText,
  Handshake,
  X,
  ChevronRight,
  TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { ErrorBanner } from "@/components/ui/error-banner";
import {
  useDeal,
  useUpdateDeal,
  useUpdateAccount,
  useDealActivities,
  useAddDealActivity,
} from "@/lib/api";
import type { DealWithAccount, DealActivity } from "@/lib/schemas";
import { DEAL_STAGES, WORKLOAD_TYPES, ACTIVITY_TYPES } from "@/lib/schemas";

// ── Stage stepper config ──────────────────────────────────────────────────────

const STAGE_ORDER_ACTIVE = ["prospect", "qualified", "proposal", "negotiating", "won"] as const;

// ── Activity icons ────────────────────────────────────────────────────────────

function ActivityIcon({ type }: { type: string }) {
  const cls = "h-4 w-4 shrink-0";
  switch (type) {
    case "call": return <Phone className={cn(cls, "text-green-400")} />;
    case "email": return <Mail className={cn(cls, "text-blue-400")} />;
    case "meeting": return <Calendar className={cn(cls, "text-purple-400")} />;
    case "proposal_sent": return <FileText className={cn(cls, "text-orange-400")} />;
    case "contract_sent": return <Handshake className={cn(cls, "text-yellow-400")} />;
    default: return <MessageSquare className={cn(cls, "text-label-tertiary")} />;
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

// ── Helpers ───────────────────────────────────────────────────────────────────

function stageBadge(stage: string): { cls: string } {
  switch (stage) {
    case "prospect": return { cls: "text-label-secondary bg-bg-elevated" };
    case "qualified": return { cls: "text-blue-400 bg-blue-400/10" };
    case "proposal": return { cls: "text-purple-400 bg-purple-400/10" };
    case "negotiating": return { cls: "text-orange-400 bg-orange-400/10" };
    case "won": return { cls: "text-green-400 bg-green-400/10" };
    case "lost": return { cls: "text-red-400 bg-red-400/10" };
    default: return { cls: "text-label-secondary bg-bg-elevated" };
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
  const now = new Date();
  const sec = Math.floor((now.getTime() - d.getTime()) / 1000);
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
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
  const currentIdx = STAGE_ORDER_ACTIVE.indexOf(currentStage as (typeof STAGE_ORDER_ACTIVE)[number]);
  const isTerminal = currentStage === "won" || currentStage === "lost";

  return (
    <div className="px-4 mb-4">
      {/* Stage steps */}
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
                onClick={() => !isTerminal && idx > currentIdx && onAdvance(stage)}
                className={cn(
                  "flex-1 py-1.5 rounded-full text-caption-2 font-semibold transition-all",
                  isCurrent && "bg-accent text-white",
                  isPast && "bg-accent/30 text-accent",
                  isFuture && !isTerminal && "bg-bg-elevated text-label-tertiary hover:bg-separator/30",
                  isTerminal && "bg-bg-elevated text-label-quaternary cursor-default",
                )}
              >
                {stage === "won" ? "Won" : stage.charAt(0).toUpperCase() + stage.slice(1)}
              </button>
              {idx < STAGE_ORDER_ACTIVE.length - 1 && (
                <ChevronRight className="h-3 w-3 text-label-quaternary shrink-0" />
              )}
            </React.Fragment>
          );
        })}
      </div>
      {/* Mark lost button */}
      {!isTerminal && (
        <button
          type="button"
          disabled={isPending}
          onClick={onMarkLost}
          className="text-caption-1 font-semibold text-red-400 bg-red-400/10 rounded-xl px-3 py-1.5 transition-opacity disabled:opacity-50"
        >
          Mark Lost
        </button>
      )}
      {currentStage === "lost" && (
        <span className="text-caption-1 text-red-400 font-semibold">Deal Lost</span>
      )}
      {currentStage === "won" && (
        <span className="text-caption-1 text-green-400 font-semibold">Deal Won 🎉</span>
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

  async function handleSubmit() {
    setError(null);
    if (!summary.trim()) {
      setError("Summary is required.");
      return;
    }
    try {
      await addActivity.mutateAsync({ activity_type: type, summary: summary.trim() });
      onClose();
    } catch (e: unknown) {
      const err = e as { message?: string };
      setError(err?.message ?? "Failed to log activity");
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg bg-chrome rounded-t-3xl p-6 pb-[calc(env(safe-area-inset-bottom)+24px)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="w-10 h-1 bg-separator/60 rounded-full mx-auto mb-5" />
        <div className="flex items-center justify-between mb-4">
          <p className="text-headline font-semibold text-label-primary">Log Activity</p>
          <button type="button" onClick={onClose} className="text-label-tertiary hover:text-label-primary">
            <X className="h-5 w-5" />
          </button>
        </div>

        {error && <p className="text-caption-1 text-red-400 mb-3 bg-red-400/10 rounded-xl px-3 py-2">{error}</p>}

        {/* Activity type */}
        <div className="mb-4">
          <label className="block text-footnote font-semibold text-label-secondary uppercase tracking-wide mb-1.5">
            Type
          </label>
          <select
            value={type}
            onChange={(e) => setType(e.target.value)}
            className="w-full bg-bg-elevated border border-separator/40 rounded-xl px-3 py-2.5 text-callout text-label-primary outline-none focus:border-accent"
          >
            {ACTIVITY_TYPES.map((t) => (
              <option key={t} value={t}>{activityLabel(t)}</option>
            ))}
          </select>
        </div>

        {/* Summary */}
        <div className="mb-6">
          <label className="block text-footnote font-semibold text-label-secondary uppercase tracking-wide mb-1.5">
            Summary *
          </label>
          <textarea
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            rows={4}
            placeholder="What happened?"
            className="w-full bg-bg-elevated border border-separator/40 rounded-xl px-3 py-2.5 text-callout text-label-primary placeholder-label-quaternary outline-none focus:border-accent resize-none"
          />
        </div>

        <button
          type="button"
          onClick={handleSubmit}
          disabled={addActivity.isPending}
          className="w-full bg-accent text-white font-semibold text-callout rounded-2xl py-3 transition-opacity disabled:opacity-50"
        >
          {addActivity.isPending ? "Logging..." : "Log Activity"}
        </button>
      </div>
    </div>
  );
}

// ── Activity Tab ──────────────────────────────────────────────────────────────

function ActivityTab({ dealId, deal }: { dealId: string; deal: DealWithAccount }) {
  const { data: activitiesData, isLoading } = useDealActivities(dealId);
  const [showLogModal, setShowLogModal] = React.useState(false);

  const activities = activitiesData?.items ?? [];

  return (
    <div className="px-4">
      <button
        type="button"
        onClick={() => setShowLogModal(true)}
        className="w-full mb-4 bg-accent/10 text-accent font-semibold text-callout rounded-2xl py-3 border border-accent/30 transition-colors hover:bg-accent/20"
      >
        + Log Activity
      </button>

      {isLoading && (
        <p className="text-caption-1 text-label-tertiary text-center py-6">Loading...</p>
      )}

      {!isLoading && activities.length === 0 && (
        <p className="text-caption-1 text-label-tertiary text-center py-8">
          No activities yet. Log your first touchpoint above.
        </p>
      )}

      <div className="space-y-3">
        {activities.map((activity: DealActivity) => (
          <div
            key={activity.id}
            className="rounded-2xl bg-chrome/80 border border-separator/40 p-3"
          >
            <div className="flex items-start gap-3">
              <div className="mt-0.5">
                <ActivityIcon type={activity.activity_type} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-caption-1 font-semibold text-label-secondary">
                    {activityLabel(activity.activity_type)}
                  </span>
                  <span className="text-caption-2 text-label-tertiary">
                    {timeAgo(activity.created_at)}
                  </span>
                </div>
                <p className="text-callout text-label-primary">{activity.summary}</p>
                {activity.created_by && (
                  <p className="text-caption-2 text-label-tertiary mt-1">{activity.created_by}</p>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {showLogModal && (
        <LogActivityModal dealId={dealId} onClose={() => setShowLogModal(false)} />
      )}
    </div>
  );
}

// ── Details Tab ───────────────────────────────────────────────────────────────

function DetailsTab({ deal }: { deal: DealWithAccount }) {
  const updateDeal = useUpdateDeal(deal.id);
  const updateAccount = useUpdateAccount(deal.account_id);

  // Account fields
  const [contactName, setContactName] = React.useState(deal.account.primary_contact_name ?? "");
  const [contactEmail, setContactEmail] = React.useState(deal.account.primary_contact_email ?? "");
  const [contactPhone, setContactPhone] = React.useState(deal.account.primary_contact_phone ?? "");
  const [industry, setIndustry] = React.useState(deal.account.industry ?? "");
  const [website, setWebsite] = React.useState(deal.account.website ?? "");

  // Deal fields
  const [workloadType, setWorkloadType] = React.useState(deal.workload_type ?? "");
  const [mwRequired, setMwRequired] = React.useState(deal.mw_required?.toString() ?? "");
  const [valueUsd, setValueUsd] = React.useState(deal.value_usd?.toString() ?? "");
  const [probabilityPct, setProbabilityPct] = React.useState(deal.probability_pct?.toString() ?? "");
  const [expectedClose, setExpectedClose] = React.useState(deal.expected_close ?? "");
  const [notes, setNotes] = React.useState(deal.notes ?? "");
  const [campusId, setCampusId] = React.useState(deal.campus_id ?? "");
  const [lostReason, setLostReason] = React.useState(deal.lost_reason ?? "");

  const [saved, setSaved] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function handleSave() {
    setError(null);
    setSaved(false);
    try {
      await updateAccount.mutateAsync({
        primary_contact_name: contactName || undefined,
        primary_contact_email: contactEmail || undefined,
        primary_contact_phone: contactPhone || undefined,
        industry: industry || undefined,
        website: website || undefined,
      });
      await updateDeal.mutateAsync({
        workload_type: workloadType || undefined,
        mw_required: mwRequired ? parseFloat(mwRequired) : undefined,
        value_usd: valueUsd ? parseFloat(valueUsd) : undefined,
        probability_pct: probabilityPct ? parseInt(probabilityPct, 10) : undefined,
        expected_close: expectedClose || undefined,
        notes: notes || undefined,
        campus_id: campusId || undefined,
        lost_reason: lostReason || undefined,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e: unknown) {
      const err = e as { message?: string };
      setError(err?.message ?? "Failed to save");
    }
  }

  const isPending = updateDeal.isPending || updateAccount.isPending;

  function Field({ label, children }: { label: string; children: React.ReactNode }) {
    return (
      <div className="mb-4">
        <label className="block text-footnote font-semibold text-label-secondary uppercase tracking-wide mb-1.5">
          {label}
        </label>
        {children}
      </div>
    );
  }

  const inputCls = "w-full bg-bg-elevated border border-separator/40 rounded-xl px-3 py-2.5 text-callout text-label-primary placeholder-label-quaternary outline-none focus:border-accent";

  return (
    <div className="px-4">
      {error && <p className="text-caption-1 text-red-400 mb-3 bg-red-400/10 rounded-xl px-3 py-2">{error}</p>}

      {/* Account section */}
      <p className="text-footnote font-bold text-label-tertiary uppercase tracking-wide mb-3">Account</p>

      <Field label="Contact Name">
        <input value={contactName} onChange={(e) => setContactName(e.target.value)} placeholder="Jane Smith" className={inputCls} />
      </Field>
      <Field label="Contact Email">
        <input type="email" value={contactEmail} onChange={(e) => setContactEmail(e.target.value)} placeholder="jane@example.com" className={inputCls} />
      </Field>
      <Field label="Contact Phone">
        <input value={contactPhone} onChange={(e) => setContactPhone(e.target.value)} placeholder="+1 555 000 0000" className={inputCls} />
      </Field>
      <Field label="Industry">
        <input value={industry} onChange={(e) => setIndustry(e.target.value)} placeholder="AI / Cloud" className={inputCls} />
      </Field>
      <Field label="Website">
        <input value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="https://..." className={inputCls} />
      </Field>

      {/* Deal section */}
      <p className="text-footnote font-bold text-label-tertiary uppercase tracking-wide mb-3 mt-6">Deal</p>

      <Field label="Workload Type">
        <select value={workloadType} onChange={(e) => setWorkloadType(e.target.value)} className={inputCls}>
          <option value="">Select...</option>
          {WORKLOAD_TYPES.map((w) => <option key={w} value={w}>{w}</option>)}
        </select>
      </Field>
      <Field label="MW Required">
        <input type="number" value={mwRequired} onChange={(e) => setMwRequired(e.target.value)} placeholder="150" className={inputCls} />
      </Field>
      <Field label="Annual Value (USD)">
        <input type="number" value={valueUsd} onChange={(e) => setValueUsd(e.target.value)} placeholder="18000000" className={inputCls} />
      </Field>
      <Field label="Probability %">
        <input type="number" min="0" max="100" value={probabilityPct} onChange={(e) => setProbabilityPct(e.target.value)} placeholder="70" className={inputCls} />
      </Field>
      <Field label="Expected Close">
        <input type="date" value={expectedClose} onChange={(e) => setExpectedClose(e.target.value)} className={inputCls} />
      </Field>
      <Field label="Notes">
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} className={cn(inputCls, "resize-none")} />
      </Field>

      {/* Won-specific: link campus */}
      {deal.stage === "won" && (
        <Field label="Linked Campus ID">
          <input value={campusId} onChange={(e) => setCampusId(e.target.value)} placeholder="campus UUID" className={inputCls} />
        </Field>
      )}

      {/* Lost-specific: lost reason */}
      {deal.stage === "lost" && (
        <Field label="Lost Reason">
          <textarea value={lostReason} onChange={(e) => setLostReason(e.target.value)} rows={2} className={cn(inputCls, "resize-none")} />
        </Field>
      )}

      <button
        type="button"
        onClick={handleSave}
        disabled={isPending}
        className="w-full bg-accent text-white font-semibold text-callout rounded-2xl py-3 transition-opacity disabled:opacity-50 mb-6"
      >
        {isPending ? "Saving..." : saved ? "Saved ✓" : "Save Changes"}
      </button>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function DealDetailPage() {
  const params = useParams();
  const router = useRouter();
  const dealId = Array.isArray(params.id) ? params.id[0] : (params.id ?? "");

  const { data: deal, error, isLoading } = useDeal(dealId);
  const updateDeal = useUpdateDeal(dealId);

  const [activeTab, setActiveTab] = React.useState<"activity" | "details">("activity");

  async function handleAdvanceStage(newStage: string) {
    await updateDeal.mutateAsync({ stage: newStage });
  }

  async function handleMarkLost() {
    await updateDeal.mutateAsync({ stage: "lost" });
  }

  const currentStage = deal?.stage ?? "prospect";
  const { cls: stageCls } = stageBadge(currentStage);

  return (
    <MobileShell>
      <TopBar
        title={deal?.name ?? "Deal"}
        left={
          <button
            type="button"
            onClick={() => router.push("/pipeline")}
            className="flex items-center gap-1 text-accent text-callout font-medium"
          >
            <ArrowLeft className="h-4 w-4" />
            Pipeline
          </button>
        }
      />

      <div className="flex-1 overflow-y-auto pb-[calc(env(safe-area-inset-bottom)+80px)]">
        {error && (
          <div className="px-4 mt-3">
            <ErrorBanner message="Failed to load deal." />
          </div>
        )}

        {isLoading && (
          <p className="text-callout text-label-tertiary text-center py-16">Loading...</p>
        )}

        {deal && (
          <>
            {/* Header */}
            <div className="px-4 pt-3 pb-4 border-b border-separator/30">
              <p className="text-title-2 font-bold text-label-primary mb-1">{deal.account.name}</p>
              <div className="flex items-center flex-wrap gap-2">
                <span className={cn("text-caption-1 font-semibold rounded-full px-2.5 py-1", stageCls)}>
                  {currentStage.charAt(0).toUpperCase() + currentStage.slice(1)}
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
                  <span className={cn(
                    "text-caption-1",
                    new Date(deal.expected_close) < new Date()
                      ? "text-red-400 font-semibold"
                      : "text-label-tertiary",
                  )}>
                    Close: {deal.expected_close}
                  </span>
                )}
              </div>
            </div>

            {/* Stage stepper */}
            <div className="pt-4">
              <StageStepper
                currentStage={currentStage}
                onAdvance={handleAdvanceStage}
                onMarkLost={handleMarkLost}
                isPending={updateDeal.isPending}
              />
            </div>

            {/* Tabs */}
            <div className="flex border-b border-separator/30 mb-4 px-4 gap-6">
              {(["activity", "details"] as const).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  onClick={() => setActiveTab(tab)}
                  className={cn(
                    "pb-2 text-callout font-semibold transition-colors capitalize",
                    activeTab === tab
                      ? "text-accent border-b-2 border-accent -mb-px"
                      : "text-label-tertiary",
                  )}
                >
                  {tab}
                </button>
              ))}
            </div>

            {/* Tab content */}
            {activeTab === "activity" ? (
              <ActivityTab dealId={dealId} deal={deal} />
            ) : (
              <DetailsTab deal={deal} />
            )}
          </>
        )}
      </div>
    </MobileShell>
  );
}
