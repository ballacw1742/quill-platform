/**
 * Tests for lib/queue-categories.ts
 *
 * Covers:
 *   - workflowToLabel: exact, prefix, and prettified-fallback cases
 *   - groupItemsByCategory: grouping + within-category sort + category sort
 *   - computeInitialExpansion: localStorage merge + force-expand on pending
 *   - classifyDecideError: 409 "already-decided", 401 "auth-required", other
 *
 * These are pure-logic tests (no DOM, no React) — runs fine in vitest
 * node environment.
 */

import { describe, it, expect } from "vitest";
import {
  workflowToLabel,
  groupItemsByCategory,
  computeInitialExpansion,
  classifyDecideError,
  type QueueCategory,
} from "../queue-categories";
import type { ApprovalItem, Lane } from "../schemas";

// ── Fixture helpers ──────────────────────────────────────────────────────────

function makeItem(
  overrides: Partial<ApprovalItem> & {
    approval_id: string;
    workflow: string;
    lane: Lane;
  },
): ApprovalItem {
  const defaults: ApprovalItem = {
    approval_id: overrides.approval_id,
    agent_id: "test-agent",
    agent_version: "0.1.0",
    workflow: overrides.workflow,
    lane: overrides.lane,
    proposed_action: { kind: "test", payload: {}, target_system: null },
    context: { project_id: "TEST", sources: [] },
    confidence: 0.8,
    escalations: [],
    priority: "normal",
    status: "pending",
    created_at: "2025-01-01T00:00:00Z",
    expires_at: null,
    decided_at: null,
    decided_by: null,
    decision_reason: null,
  };
  return { ...defaults, ...overrides };
}

// ── workflowToLabel ──────────────────────────────────────────────────────────

describe("workflowToLabel", () => {
  it("maps exact matches correctly", () => {
    expect(workflowToLabel("aace_classification.publish")).toBe("AACE Classifications");
    expect(workflowToLabel("cost_schedule_package.publish")).toBe("Cost & Schedule Packages");
  });

  it("maps rfi.* prefix variants to 'RFIs'", () => {
    expect(workflowToLabel("rfi.draft")).toBe("RFIs");
    expect(workflowToLabel("rfi.full_triage")).toBe("RFIs");
    expect(workflowToLabel("rfi.anything_else")).toBe("RFIs");
  });

  it("maps submittal.* prefix variants to 'Submittals'", () => {
    expect(workflowToLabel("submittal.review")).toBe("Submittals");
    expect(workflowToLabel("submittal.full_review")).toBe("Submittals");
  });

  it("maps dfr.* prefix variants to 'Daily Field Reports'", () => {
    expect(workflowToLabel("dfr.synthesis")).toBe("Daily Field Reports");
    expect(workflowToLabel("dfr.anything")).toBe("Daily Field Reports");
  });

  it("maps po.* prefix variants to 'Purchase Orders'", () => {
    expect(workflowToLabel("po.update")).toBe("Purchase Orders");
    expect(workflowToLabel("po.anything")).toBe("Purchase Orders");
  });

  it("prettifies unknown workflows (dots/underscores → title-case words)", () => {
    expect(workflowToLabel("custom.thing")).toBe("Custom Thing");
    expect(workflowToLabel("my_workflow.action")).toBe("My Workflow Action");
    expect(workflowToLabel("singleword")).toBe("Singleword");
  });

  it("returns 'Other' for null/undefined/empty", () => {
    expect(workflowToLabel(null)).toBe("Other");
    expect(workflowToLabel(undefined)).toBe("Other");
    expect(workflowToLabel("")).toBe("Other");
  });
});

// ── groupItemsByCategory ─────────────────────────────────────────────────────

describe("groupItemsByCategory", () => {
  it("groups items with 2+ workflow types into separate categories", () => {
    const items = [
      makeItem({ approval_id: "a1", workflow: "rfi.draft", lane: "tier-1-spotcheck" }),
      makeItem({ approval_id: "a2", workflow: "rfi.full_triage", lane: "tier-1-spotcheck" }),
      makeItem({ approval_id: "a3", workflow: "submittal.review", lane: "tier-1-spotcheck" }),
    ];

    const categories = groupItemsByCategory(items);

    // Should have exactly 2 categories: RFIs and Submittals
    expect(categories).toHaveLength(2);

    const labels = categories.map((c) => c.label);
    expect(labels).toContain("RFIs");
    expect(labels).toContain("Submittals");
  });

  it("groups both rfi variants under 'RFIs'", () => {
    const items = [
      makeItem({ approval_id: "r1", workflow: "rfi.draft", lane: "tier-1-spotcheck" }),
      makeItem({ approval_id: "r2", workflow: "rfi.full_triage", lane: "tier-2-auto" }),
    ];

    const categories = groupItemsByCategory(items);
    expect(categories).toHaveLength(1);
    expect(categories[0].label).toBe("RFIs");
    expect(categories[0].items).toHaveLength(2);
  });

  it("returns empty array for empty input", () => {
    expect(groupItemsByCategory([])).toEqual([]);
  });

  it("counts pending items correctly", () => {
    const items = [
      makeItem({ approval_id: "p1", workflow: "rfi.draft", lane: "tier-1-spotcheck", status: "pending" }),
      makeItem({ approval_id: "p2", workflow: "rfi.draft", lane: "tier-1-spotcheck", status: "approved" }),
      makeItem({ approval_id: "p3", workflow: "submittal.review", lane: "tier-1-spotcheck", status: "rejected" }),
    ];

    const categories = groupItemsByCategory(items);
    const rfi = categories.find((c) => c.label === "RFIs");
    const sub = categories.find((c) => c.label === "Submittals");

    expect(rfi?.pendingCount).toBe(1);
    expect(rfi?.hasPending).toBe(true);
    expect(sub?.pendingCount).toBe(0);
    expect(sub?.hasPending).toBe(false);
  });

  it("sorts categories: pending-first, then A-Z", () => {
    const items = [
      // Submittals: no pending
      makeItem({ approval_id: "s1", workflow: "submittal.review", lane: "tier-1-spotcheck", status: "approved" }),
      // AACE: pending
      makeItem({ approval_id: "a1", workflow: "aace_classification.publish", lane: "tier-1-spotcheck", status: "pending" }),
      // RFIs: no pending
      makeItem({ approval_id: "r1", workflow: "rfi.draft", lane: "tier-1-spotcheck", status: "approved" }),
    ];

    const categories = groupItemsByCategory(items);
    const labels = categories.map((c) => c.label);

    // AACE Classifications (pending) → first
    expect(labels[0]).toBe("AACE Classifications");
    // Then RFIs and Submittals alphabetically
    expect(labels[1]).toBe("RFIs");
    expect(labels[2]).toBe("Submittals");
  });

  it("sorts items within a category: lane priority first, then newest-first", () => {
    const items = [
      makeItem({
        approval_id: "auto1",
        workflow: "rfi.draft",
        lane: "tier-2-auto",
        created_at: "2025-01-03T00:00:00Z",
      }),
      makeItem({
        approval_id: "mandatory1",
        workflow: "rfi.draft",
        lane: "tier-0-mandatory",
        created_at: "2025-01-01T00:00:00Z",
      }),
      makeItem({
        approval_id: "spot1",
        workflow: "rfi.draft",
        lane: "tier-1-spotcheck",
        created_at: "2025-01-02T00:00:00Z",
      }),
    ];

    const categories = groupItemsByCategory(items);
    const rfi = categories.find((c) => c.label === "RFIs")!;
    const ids = rfi.items.map((i) => i.approval_id);

    // tier-0 first, then tier-1, then tier-2
    expect(ids).toEqual(["mandatory1", "spot1", "auto1"]);
  });
});

// ── computeInitialExpansion ──────────────────────────────────────────────────

describe("computeInitialExpansion", () => {
  const pendingCat: QueueCategory = {
    label: "RFIs",
    items: [],
    pendingCount: 2,
    hasPending: true,
  };
  const decidedCat: QueueCategory = {
    label: "Submittals",
    items: [],
    pendingCount: 0,
    hasPending: false,
  };

  it("force-expands categories with pending items regardless of stored state", () => {
    const expanded = computeInitialExpansion([pendingCat, decidedCat], null);
    expect(expanded.has("RFIs")).toBe(true);
  });

  it("does not expand all-decided categories when no stored state", () => {
    const expanded = computeInitialExpansion([pendingCat, decidedCat], null);
    expect(expanded.has("Submittals")).toBe(false);
  });

  it("respects stored expansion for all-decided categories", () => {
    const expanded = computeInitialExpansion([decidedCat], ["Submittals"]);
    expect(expanded.has("Submittals")).toBe(true);
  });

  it("force-expands pending categories even when stored state says collapsed", () => {
    // stored is an empty array (user collapsed everything)
    const expanded = computeInitialExpansion([pendingCat], []);
    expect(expanded.has("RFIs")).toBe(true);
  });

  it("does not add labels for categories not in the list", () => {
    const expanded = computeInitialExpansion([decidedCat], ["RFIs", "Submittals"]);
    // RFIs is not in the categories list, so it should not appear
    expect(expanded.has("RFIs")).toBe(false);
    expect(expanded.has("Submittals")).toBe(true);
  });
});

// ── classifyDecideError ──────────────────────────────────────────────────────

describe("classifyDecideError", () => {
  it("classifies 409 as 'already-decided'", () => {
    const err = { status: 409, message: "Conflict" };
    expect(classifyDecideError(err)).toBe("already-decided");
  });

  it("classifies 401 as 'auth-required'", () => {
    const err = { status: 401, message: "Unauthorized" };
    expect(classifyDecideError(err)).toBe("auth-required");
  });

  it("classifies other statuses as 'unknown'", () => {
    expect(classifyDecideError({ status: 500, message: "Server error" })).toBe("unknown");
    expect(classifyDecideError({ status: 422, message: "Validation" })).toBe("unknown");
  });

  it("classifies non-error objects as 'unknown'", () => {
    expect(classifyDecideError(null)).toBe("unknown");
    expect(classifyDecideError(undefined)).toBe("unknown");
    expect(classifyDecideError("string error")).toBe("unknown");
    expect(classifyDecideError(new Error("plain error"))).toBe("unknown");
  });

  it("classifies actual ApiError-shaped objects (with status) correctly", () => {
    // Simulate ApiError from api.ts without importing it (avoids "use client" issues).
    class FakeApiError extends Error {
      status: number;
      constructor(status: number, msg: string) {
        super(msg);
        this.status = status;
      }
    }
    expect(classifyDecideError(new FakeApiError(409, "Already decided"))).toBe("already-decided");
    expect(classifyDecideError(new FakeApiError(401, "Unauthorized"))).toBe("auth-required");
    expect(classifyDecideError(new FakeApiError(500, "Server error"))).toBe("unknown");
  });
});
