/**
 * today.ts — Pure derivation helpers for the /today daily-brief page.
 *
 * All functions are side-effect-free and take plain data as arguments
 * so they can be unit-tested without React or a DOM.
 */

import type { ApprovalItem } from "@/lib/schemas";
import type { EstimateListItem } from "@/lib/api";
import type { ContractListItem } from "@/lib/schemas";

// ── Lane priority ranking (lower = more urgent) ─────────────────────────────

const LANE_PRIORITY: Record<string, number> = {
  "tier-0-mandatory": 0,
  "tier-1-spotcheck": 1,
  "tier-2-auto": 2,
};

// ── Public types ─────────────────────────────────────────────────────────────

export type InFlightItem = {
  /** Stable ID for the item (upload_id for estimates/contracts). */
  id: string;
  kind: "estimate" | "contract";
  label: string;
  /** Fine-grained status string from the API. */
  status: string;
  /** Target route for the tap action. */
  href: string;
  /** ISO-8601 start time (created_at). Used for recency sorting. */
  started_at: string;
};

export type ShippedItem = {
  id: string;
  kind: "approval" | "estimate" | "contract";
  label: string;
  /** ISO-8601 completion timestamp (decided_at, updated_at, or created_at). */
  ts: string;
  href: string;
};

// ── Derivation functions ─────────────────────────────────────────────────────

/**
 * Returns top 5 pending approvals sorted by lane priority (tier-0 first),
 * then by age (oldest first = waiting longest).
 */
export function deriveNeedsSignoff(approvals: ApprovalItem[]): ApprovalItem[] {
  return approvals
    .filter((a) => a.status === "pending")
    .sort((a, b) => {
      const laneDiff =
        (LANE_PRIORITY[a.lane] ?? 1) - (LANE_PRIORITY[b.lane] ?? 1);
      if (laneDiff !== 0) return laneDiff;
      // Within the same lane: oldest first (most urgent)
      return +new Date(a.created_at) - +new Date(b.created_at);
    })
    .slice(0, 5);
}

/**
 * Returns the total count of pending approvals (for "View all N →" footer).
 */
export function countPendingApprovals(approvals: ApprovalItem[]): number {
  return approvals.filter((a) => a.status === "pending").length;
}

/** In-flight contract statuses that indicate active processing. */
const IN_FLIGHT_CONTRACT_STATUSES = new Set([
  "extracting",
  "reviewing",
  "drafting",
]);

/**
 * Combines in-flight estimates + contracts into a single list, sorted by
 * started_at descending (most recent first), capped at 5.
 */
export function deriveInFlight(
  estimates: EstimateListItem[],
  contracts: ContractListItem[],
): InFlightItem[] {
  const estimateItems: InFlightItem[] = estimates
    .filter((e) => e.status_hint === "in_flight")
    .map((e) => ({
      id: e.upload_id,
      kind: "estimate" as const,
      label: e.project_label || "Untitled estimate",
      status: e.status,
      href: `/estimates/${e.upload_id}`,
      started_at: e.created_at,
    }));

  const contractItems: InFlightItem[] = contracts
    .filter((c) => IN_FLIGHT_CONTRACT_STATUSES.has(c.status))
    .map((c) => ({
      id: c.upload_id,
      kind: "contract" as const,
      label: c.project_label || "Untitled contract",
      status: c.status,
      href: `/contracts/${c.upload_id}`,
      started_at: c.created_at ?? new Date(0).toISOString(),
    }));

  return [...estimateItems, ...contractItems]
    .sort((a, b) => +new Date(b.started_at) - +new Date(a.started_at))
    .slice(0, 5);
}

/**
 * Items that completed within the last 24 hours:
 *  - Approvals approved/executed with decided_at in last 24h
 *  - Estimates with status "done" with created_at in last 24h (proxy — no
 *    updated_at on EstimateListItem; see KNOWN_ISSUES)
 *  - Contracts with status "drafted" with updated_at (or created_at) in last 24h
 *
 * Sorted by completion time descending, capped at 5.
 */
export function deriveRecentlyShipped(
  approvals: ApprovalItem[],
  estimates: EstimateListItem[],
  contracts: ContractListItem[],
  now: number,
): ShippedItem[] {
  const cutoff = now - 24 * 60 * 60 * 1000;

  const shippedApprovals: ShippedItem[] = approvals
    .filter(
      (a) =>
        (a.status === "approved" || a.status === "executed") &&
        a.decided_at != null &&
        +new Date(a.decided_at) > cutoff,
    )
    .map((a) => ({
      id: a.approval_id,
      kind: "approval" as const,
      label: a.summary ?? a.workflow ?? "Approval",
      ts: a.decided_at!,
      href: "/queue",
    }));

  const shippedEstimates: ShippedItem[] = estimates
    .filter((e) => e.status === "done" && +new Date(e.created_at) > cutoff)
    .map((e) => ({
      id: e.upload_id,
      kind: "estimate" as const,
      label: e.project_label || "Untitled estimate",
      ts: e.created_at,
      href: `/estimates/${e.upload_id}`,
    }));

  const shippedContracts: ShippedItem[] = contracts
    .filter((c) => {
      const ts = c.updated_at ?? c.created_at;
      return c.status === "drafted" && ts != null && +new Date(ts) > cutoff;
    })
    .map((c) => ({
      id: c.upload_id,
      kind: "contract" as const,
      label: c.project_label || "Untitled contract",
      ts: c.updated_at ?? c.created_at ?? new Date().toISOString(),
      href: `/contracts/${c.upload_id}`,
    }));

  return [...shippedApprovals, ...shippedEstimates, ...shippedContracts]
    .sort((a, b) => +new Date(b.ts) - +new Date(a.ts))
    .slice(0, 5);
}

/**
 * Pending approvals that have been waiting more than 24 hours — stale/forgotten.
 * Sorted oldest-first (most stale at top), capped at 5.
 */
export function deriveNeedsAttention(
  approvals: ApprovalItem[],
  now: number,
): ApprovalItem[] {
  const cutoff = now - 24 * 60 * 60 * 1000;
  return approvals
    .filter((a) => a.status === "pending" && +new Date(a.created_at) < cutoff)
    .sort((a, b) => +new Date(a.created_at) - +new Date(b.created_at)) // oldest first
    .slice(0, 5);
}

// ── Shared formatting helpers ─────────────────────────────────────────────────

/**
 * Returns a compact age label: "2h ago", "yesterday", "3 days", etc.
 * Relative to `now` (defaults to Date.now()).
 */
export function formatAge(isoTs: string, now = Date.now()): string {
  const ms = now - +new Date(isoTs);
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return "just now";
  const mins = Math.floor(seconds / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

/**
 * Short stale-age label for the Needs Attention section chip.
 * Examples: "2 days", "5 days".
 */
export function formatStaleAge(isoTs: string, now = Date.now()): string {
  const ms = now - +new Date(isoTs);
  const hours = Math.floor(ms / 3_600_000);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return `${days} day${days !== 1 ? "s" : ""}`;
}

/**
 * Human-readable status line for an in-flight estimate or contract row.
 */
export function formatInFlightLabel(item: InFlightItem, now = Date.now()): string {
  const age = formatAge(item.started_at, now);
  const verb =
    item.status === "drafting"
      ? "Drafting"
      : item.status === "reviewing"
        ? "Reviewing"
        : item.status === "extracting"
          ? "Extracting"
          : item.status === "classifying"
            ? "Classifying"
            : item.status === "estimating"
              ? "Estimating"
              : item.status === "queued"
                ? "Queued"
                : "Processing";

  const kindLabel = item.kind === "contract" ? "subcontract" : "estimate";
  return `${verb} ${item.label} (${kindLabel}) · ${age}`;
}

/**
 * Human-readable line for a recently-shipped item row.
 */
export function formatShippedLabel(item: ShippedItem, now = Date.now()): string {
  const age = formatAge(item.ts, now);
  if (item.kind === "approval") {
    return `Approved ${item.label} · ${age}`;
  }
  if (item.kind === "contract") {
    return `Drafted ${item.label} · ${age}`;
  }
  return `Completed ${item.label} · ${age}`;
}
