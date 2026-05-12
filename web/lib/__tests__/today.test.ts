/**
 * Tests for lib/today.ts derivation helpers.
 *
 * Covers:
 *   - deriveNeedsSignoff: top-5, lane sort, then age sort
 *   - deriveInFlight: combines estimates + contracts, sorted by started_at desc, max 5
 *   - deriveRecentlyShipped: filters to last 24h across all three sources
 *   - deriveNeedsAttention: pending items older than 24h, oldest first, max 5
 *   - formatAge / formatStaleAge helpers
 *
 * Pure-logic tests — no DOM, no React, no API calls.
 */

import { describe, it, expect } from "vitest";
import {
  deriveNeedsSignoff,
  deriveInFlight,
  deriveRecentlyShipped,
  deriveNeedsAttention,
  countPendingApprovals,
  formatAge,
  formatStaleAge,
  formatInFlightLabel,
  formatShippedLabel,
} from "../today";
import type { ApprovalItem, Lane } from "../schemas";
import type { EstimateListItem } from "../api";
import type { ContractListItem } from "../schemas";

// ── Fixture helpers ──────────────────────────────────────────────────────────

let _seq = 0;

function makeApproval(
  overrides: Partial<ApprovalItem> & { lane: Lane; status: ApprovalItem["status"] },
): ApprovalItem {
  _seq++;
  const base: ApprovalItem = {
    approval_id: `approval-${_seq}`,
    agent_id: "test-agent",
    agent_version: "0.1.0",
    workflow: "test-workflow",
    lane: overrides.lane,
    proposed_action: {
      kind: "test",
      payload: {},
    },
    context: {
      project_id: "QPB1",
      sources: [],
    },
    confidence: 0.9,
    status: overrides.status,
    created_at: new Date().toISOString(),
  } as ApprovalItem;
  return Object.assign(base, overrides);
}

function makeEstimate(
  overrides: Partial<EstimateListItem> & {
    status_hint: EstimateListItem["status_hint"];
    status: EstimateListItem["status"];
  },
): EstimateListItem {
  _seq++;
  const base: EstimateListItem = {
    upload_id: `est-${_seq}`,
    project_label: `Estimate ${_seq}`,
    status_hint: overrides.status_hint,
    status: overrides.status,
    created_at: new Date().toISOString(),
    document_id: `doc-${_seq}`,
    package_document_id: null,
    classification_document_id: null,
  };
  return Object.assign(base, overrides);
}

function makeContract(
  overrides: Partial<ContractListItem> & { status: string },
): ContractListItem {
  _seq++;
  const base: ContractListItem = {
    upload_id: `con-${_seq}`,
    project_label: `Contract ${_seq}`,
    status: overrides.status,
    source: "upload",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  } as ContractListItem;
  return Object.assign(base, overrides);
}

function hoursAgo(h: number): string {
  return new Date(Date.now() - h * 3_600_000).toISOString();
}
function daysAgo(d: number): string {
  return hoursAgo(d * 24);
}

// ── deriveNeedsSignoff ───────────────────────────────────────────────────────

describe("deriveNeedsSignoff", () => {
  it("returns only pending approvals", () => {
    const items = [
      makeApproval({ lane: "tier-1-spotcheck", status: "pending" }),
      makeApproval({ lane: "tier-1-spotcheck", status: "approved" }),
      makeApproval({ lane: "tier-0-mandatory", status: "rejected" }),
    ];
    const result = deriveNeedsSignoff(items);
    expect(result).toHaveLength(1);
    expect(result[0].status).toBe("pending");
  });

  it("sorts tier-0 before tier-1 before tier-2", () => {
    const t2 = makeApproval({ lane: "tier-2-auto", status: "pending", created_at: hoursAgo(10) });
    const t1 = makeApproval({ lane: "tier-1-spotcheck", status: "pending", created_at: hoursAgo(5) });
    const t0 = makeApproval({ lane: "tier-0-mandatory", status: "pending", created_at: hoursAgo(1) });
    const result = deriveNeedsSignoff([t2, t1, t0]);
    expect(result[0].lane).toBe("tier-0-mandatory");
    expect(result[1].lane).toBe("tier-1-spotcheck");
    expect(result[2].lane).toBe("tier-2-auto");
  });

  it("within the same lane, sorts oldest first (longest waiting)", () => {
    const older = makeApproval({ lane: "tier-1-spotcheck", status: "pending", created_at: hoursAgo(10) });
    const newer = makeApproval({ lane: "tier-1-spotcheck", status: "pending", created_at: hoursAgo(1) });
    const result = deriveNeedsSignoff([newer, older]);
    expect(result[0].approval_id).toBe(older.approval_id);
  });

  it("caps at 5 items", () => {
    const items = Array.from({ length: 10 }, () =>
      makeApproval({ lane: "tier-1-spotcheck", status: "pending" }),
    );
    expect(deriveNeedsSignoff(items)).toHaveLength(5);
  });

  it("returns empty array when no pending approvals", () => {
    const items = [makeApproval({ lane: "tier-1-spotcheck", status: "approved" })];
    expect(deriveNeedsSignoff(items)).toHaveLength(0);
  });
});

// ── countPendingApprovals ────────────────────────────────────────────────────

describe("countPendingApprovals", () => {
  it("counts all pending regardless of lane", () => {
    const items = [
      makeApproval({ lane: "tier-0-mandatory", status: "pending" }),
      makeApproval({ lane: "tier-1-spotcheck", status: "pending" }),
      makeApproval({ lane: "tier-2-auto", status: "approved" }),
    ];
    expect(countPendingApprovals(items)).toBe(2);
  });
});

// ── deriveInFlight ───────────────────────────────────────────────────────────

describe("deriveInFlight", () => {
  it("includes estimates with status_hint in_flight", () => {
    const est = makeEstimate({ status_hint: "in_flight", status: "extracting" });
    const result = deriveInFlight([est], []);
    expect(result).toHaveLength(1);
    expect(result[0].kind).toBe("estimate");
    expect(result[0].id).toBe(est.upload_id);
  });

  it("excludes estimates that are done, classified, or failed", () => {
    const done = makeEstimate({ status_hint: "published", status: "done" });
    const failed = makeEstimate({ status_hint: "failed", status: "failed" });
    const classified = makeEstimate({ status_hint: "classified", status: "done" });
    expect(deriveInFlight([done, failed, classified], [])).toHaveLength(0);
  });

  it("includes contracts with extracting, reviewing, drafting status", () => {
    const c1 = makeContract({ status: "extracting" });
    const c2 = makeContract({ status: "reviewing" });
    const c3 = makeContract({ status: "drafting" });
    const result = deriveInFlight([], [c1, c2, c3]);
    expect(result).toHaveLength(3);
    expect(result.every((r) => r.kind === "contract")).toBe(true);
  });

  it("excludes contracts with other statuses", () => {
    const uploaded = makeContract({ status: "uploaded" });
    const drafted = makeContract({ status: "drafted" });
    const failed = makeContract({ status: "failed" });
    expect(deriveInFlight([], [uploaded, drafted, failed])).toHaveLength(0);
  });

  it("combines estimates and contracts and sorts by started_at descending", () => {
    const old = makeEstimate({ status_hint: "in_flight", status: "extracting", created_at: hoursAgo(10) });
    const recent = makeContract({ status: "drafting", created_at: hoursAgo(1) });
    const result = deriveInFlight([old], [recent]);
    expect(result[0].id).toBe(recent.upload_id); // most recent first
    expect(result[1].id).toBe(old.upload_id);
  });

  it("caps at 5 items", () => {
    const ests = Array.from({ length: 3 }, () =>
      makeEstimate({ status_hint: "in_flight", status: "estimating" }),
    );
    const cons = Array.from({ length: 4 }, () =>
      makeContract({ status: "reviewing" }),
    );
    expect(deriveInFlight(ests, cons)).toHaveLength(5);
  });
});

// ── deriveRecentlyShipped ────────────────────────────────────────────────────

describe("deriveRecentlyShipped", () => {
  const now = Date.now();

  it("includes approved/executed approvals with decided_at within 24h", () => {
    const approved = makeApproval({
      lane: "tier-1-spotcheck",
      status: "approved",
      decided_at: hoursAgo(2),
    });
    const executed = makeApproval({
      lane: "tier-2-auto",
      status: "executed",
      decided_at: hoursAgo(12),
    });
    const result = deriveRecentlyShipped([approved, executed], [], [], now);
    expect(result).toHaveLength(2);
    expect(result.every((r) => r.kind === "approval")).toBe(true);
  });

  it("excludes approvals decided more than 24h ago", () => {
    const old = makeApproval({
      lane: "tier-1-spotcheck",
      status: "approved",
      decided_at: daysAgo(2),
    });
    expect(deriveRecentlyShipped([old], [], [], now)).toHaveLength(0);
  });

  it("excludes approvals without decided_at", () => {
    const pending = makeApproval({
      lane: "tier-1-spotcheck",
      status: "pending",
      decided_at: null,
    });
    expect(deriveRecentlyShipped([pending], [], [], now)).toHaveLength(0);
  });

  it("includes done estimates created within 24h", () => {
    const est = makeEstimate({ status_hint: "published", status: "done", created_at: hoursAgo(5) });
    const result = deriveRecentlyShipped([], [est], [], now);
    expect(result).toHaveLength(1);
    expect(result[0].kind).toBe("estimate");
  });

  it("excludes done estimates older than 24h", () => {
    const old = makeEstimate({ status_hint: "published", status: "done", created_at: daysAgo(2) });
    expect(deriveRecentlyShipped([], [old], [], now)).toHaveLength(0);
  });

  it("includes drafted contracts updated within 24h", () => {
    const c = makeContract({ status: "drafted", updated_at: hoursAgo(3) });
    const result = deriveRecentlyShipped([], [], [c], now);
    expect(result).toHaveLength(1);
    expect(result[0].kind).toBe("contract");
  });

  it("excludes drafted contracts updated more than 24h ago", () => {
    const old = makeContract({ status: "drafted", updated_at: daysAgo(2) });
    expect(deriveRecentlyShipped([], [], [old], now)).toHaveLength(0);
  });

  it("sorts by completion time descending", () => {
    const older = makeApproval({
      lane: "tier-1-spotcheck",
      status: "approved",
      decided_at: hoursAgo(10),
    });
    const newer = makeApproval({
      lane: "tier-1-spotcheck",
      status: "approved",
      decided_at: hoursAgo(1),
    });
    const result = deriveRecentlyShipped([older, newer], [], [], now);
    // newer decided_at should come first
    expect(+new Date(result[0].ts)).toBeGreaterThan(+new Date(result[1].ts));
  });

  it("caps at 5 items", () => {
    const approvals = Array.from({ length: 6 }, () =>
      makeApproval({
        lane: "tier-1-spotcheck",
        status: "approved",
        decided_at: hoursAgo(1),
      }),
    );
    expect(deriveRecentlyShipped(approvals, [], [], now)).toHaveLength(5);
  });
});

// ── deriveNeedsAttention ─────────────────────────────────────────────────────

describe("deriveNeedsAttention", () => {
  const now = Date.now();

  it("returns pending approvals older than 24h", () => {
    const stale = makeApproval({
      lane: "tier-1-spotcheck",
      status: "pending",
      created_at: daysAgo(2),
    });
    const fresh = makeApproval({
      lane: "tier-1-spotcheck",
      status: "pending",
      created_at: hoursAgo(1),
    });
    const result = deriveNeedsAttention([stale, fresh], now);
    expect(result).toHaveLength(1);
    expect(result[0].approval_id).toBe(stale.approval_id);
  });

  it("excludes non-pending approvals even if old", () => {
    const old = makeApproval({
      lane: "tier-1-spotcheck",
      status: "approved",
      decided_at: daysAgo(3),
      created_at: daysAgo(4),
    });
    expect(deriveNeedsAttention([old], now)).toHaveLength(0);
  });

  it("sorts oldest first (most stale at top)", () => {
    const twoDays = makeApproval({
      lane: "tier-1-spotcheck",
      status: "pending",
      created_at: daysAgo(2),
    });
    const fiveDays = makeApproval({
      lane: "tier-1-spotcheck",
      status: "pending",
      created_at: daysAgo(5),
    });
    const result = deriveNeedsAttention([twoDays, fiveDays], now);
    expect(result[0].approval_id).toBe(fiveDays.approval_id);
  });

  it("caps at 5 items", () => {
    const items = Array.from({ length: 8 }, () =>
      makeApproval({
        lane: "tier-1-spotcheck",
        status: "pending",
        created_at: daysAgo(3),
      }),
    );
    expect(deriveNeedsAttention(items, now)).toHaveLength(5);
  });

  it("returns empty array when no stale approvals", () => {
    const fresh = makeApproval({
      lane: "tier-1-spotcheck",
      status: "pending",
      created_at: hoursAgo(2),
    });
    expect(deriveNeedsAttention([fresh], now)).toHaveLength(0);
  });
});

// ── formatAge ────────────────────────────────────────────────────────────────

describe("formatAge", () => {
  const now = Date.now();

  it("returns 'just now' for < 60s", () => {
    expect(formatAge(new Date(now - 30_000).toISOString(), now)).toBe("just now");
  });

  it("returns minutes for < 60 min", () => {
    expect(formatAge(new Date(now - 5 * 60_000).toISOString(), now)).toBe("5m ago");
  });

  it("returns hours for < 24h", () => {
    expect(formatAge(new Date(now - 3 * 3_600_000).toISOString(), now)).toBe("3h ago");
  });

  it("returns 'yesterday' for ~1 day", () => {
    expect(formatAge(new Date(now - 25 * 3_600_000).toISOString(), now)).toBe("yesterday");
  });

  it("returns 'N days ago' for > 1 day", () => {
    expect(formatAge(new Date(now - 3 * 86_400_000).toISOString(), now)).toBe("3 days ago");
  });
});

// ── formatStaleAge ───────────────────────────────────────────────────────────

describe("formatStaleAge", () => {
  const now = Date.now();

  it("returns hours when < 24h", () => {
    expect(formatStaleAge(new Date(now - 5 * 3_600_000).toISOString(), now)).toBe("5h");
  });

  it("returns '1 day' singular", () => {
    expect(formatStaleAge(new Date(now - 27 * 3_600_000).toISOString(), now)).toBe("1 day");
  });

  it("returns 'N days' plural", () => {
    expect(formatStaleAge(new Date(now - 3 * 86_400_000).toISOString(), now)).toBe("3 days");
  });
});

// ── formatInFlightLabel ──────────────────────────────────────────────────────

describe("formatInFlightLabel", () => {
  it("renders verb + label + kind + age", () => {
    const now = Date.now();
    const item = {
      id: "c1",
      kind: "contract" as const,
      label: "Test Contract",
      status: "drafting",
      href: "/contracts/c1",
      started_at: new Date(now - 3_600_000).toISOString(),
    };
    const label = formatInFlightLabel(item, now);
    expect(label).toContain("Drafting");
    expect(label).toContain("Test Contract");
    expect(label).toContain("subcontract");
    expect(label).toContain("1h ago");
  });
});

// ── formatShippedLabel ───────────────────────────────────────────────────────

describe("formatShippedLabel", () => {
  it("uses 'Approved' for approval kind", () => {
    const now = Date.now();
    const item = {
      id: "a1",
      kind: "approval" as const,
      label: "AACE Classification",
      ts: new Date(now - 2 * 3_600_000).toISOString(),
      href: "/queue",
    };
    expect(formatShippedLabel(item, now)).toContain("Approved");
    expect(formatShippedLabel(item, now)).toContain("AACE Classification");
  });

  it("uses 'Drafted' for contract kind", () => {
    const now = Date.now();
    const item = {
      id: "c1",
      kind: "contract" as const,
      label: "Subcontract",
      ts: new Date(now - 3_600_000).toISOString(),
      href: "/contracts/c1",
    };
    expect(formatShippedLabel(item, now)).toContain("Drafted");
  });
});
