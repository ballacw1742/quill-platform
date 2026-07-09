/**
 * Phase 5 versioning lib tests (agent-cloud/AUTHORING_MATURITY.md).
 * Pure Zod schema validation — no network, no React.
 */
import { describe, expect, it } from "vitest";

import {
  AgentDetailSchema,
  AgentVersionDiffSchema,
  AgentVersionDetailSchema,
  AgentVersionItemSchema,
  AgentVersionListSchema,
  DiffChangeSchema,
} from "@/lib/agent-cloud";

// ─── AgentVersionItemSchema ────────────────────────────────────────────────

describe("AgentVersionItemSchema", () => {
  it("parses the current head with rolled_back_from", () => {
    const item = AgentVersionItemSchema.parse({
      version: 3,
      change_action: "rolledback",
      changed_fields: ["system_prompt", "tools"],
      rolled_back_from: 1,
      is_current: true,
      created_at: "2026-07-09T12:00:00+00:00",
    });
    expect(item.is_current).toBe(true);
    expect(item.rolled_back_from).toBe(1);
    expect(item.version).toBe(3);
  });

  it("parses a historic row with null rolled_back_from", () => {
    const item = AgentVersionItemSchema.parse({
      version: 1,
      change_action: "created",
      changed_fields: ["*"],
      rolled_back_from: null,
      is_current: false,
      created_at: "2026-07-01T10:00:00+00:00",
    });
    expect(item.rolled_back_from).toBeNull();
    expect(item.change_action).toBe("created");
  });
});

// ─── AgentVersionListSchema ────────────────────────────────────────────────

describe("AgentVersionListSchema", () => {
  it("parses a multi-version list envelope", () => {
    const list = AgentVersionListSchema.parse({
      items: [
        {
          version: 2,
          change_action: "updated",
          changed_fields: ["model"],
          rolled_back_from: null,
          is_current: true,
          created_at: "2026-07-09T12:00:00+00:00",
        },
        {
          version: 1,
          change_action: "created",
          changed_fields: ["*"],
          rolled_back_from: null,
          is_current: false,
          created_at: "2026-07-01T10:00:00+00:00",
        },
      ],
      total: 2,
      limit: 100,
      offset: 0,
    });
    expect(list.items).toHaveLength(2);
    expect(list.items[0].is_current).toBe(true);
    expect(list.total).toBe(2);
  });

  it("parses an empty list (never-updated agent)", () => {
    const list = AgentVersionListSchema.parse({
      items: [],
      total: 0,
      limit: 100,
      offset: 0,
    });
    expect(list.items).toHaveLength(0);
  });
});

// ─── AgentVersionDetailSchema ──────────────────────────────────────────────

describe("AgentVersionDetailSchema", () => {
  it("parses a historic version snapshot", () => {
    const detail = AgentVersionDetailSchema.parse({
      agent_id: "research",
      version: 2,
      system_prompt: "You are a research assistant.",
      model: "claude-fable-5",
      tools: ["get_time"],
      memory_policy: "off",
      budget_monthly_usd: 10.0,
      enabled: true,
      is_current: false,
      created_at: "2026-07-05T08:00:00+00:00",
    });
    expect(detail.agent_id).toBe("research");
    expect(detail.version).toBe(2);
    expect(detail.is_current).toBe(false);
  });

  it("parses the current version detail", () => {
    const detail = AgentVersionDetailSchema.parse({
      agent_id: "ops",
      version: 5,
      system_prompt: "Latest prompt.",
      model: "gemini-2.5-pro",
      tools: ["web_search", "get_time"],
      memory_policy: "auto_recall",
      budget_monthly_usd: 20.0,
      enabled: true,
      is_current: true,
      created_at: "2026-07-09T14:00:00+00:00",
    });
    expect(detail.is_current).toBe(true);
    expect(detail.tools).toContain("web_search");
  });
});

// ─── DiffChangeSchema ──────────────────────────────────────────────────────

describe("DiffChangeSchema", () => {
  it("accepts string from/to (system_prompt)", () => {
    const c = DiffChangeSchema.parse({
      field: "system_prompt",
      from: "old prompt",
      to: "new and improved prompt",
    });
    expect(c.field).toBe("system_prompt");
    expect(c.from).toBe("old prompt");
  });

  it("accepts array from/to (tools)", () => {
    const c = DiffChangeSchema.parse({
      field: "tools",
      from: ["get_time"],
      to: ["get_time", "quill_finance_summary"],
    });
    expect(Array.isArray(c.to)).toBe(true);
    expect(c.to).toEqual(["get_time", "quill_finance_summary"]);
  });

  it("accepts boolean from/to (enabled)", () => {
    const c = DiffChangeSchema.parse({ field: "enabled", from: false, to: true });
    expect(c.to).toBe(true);
  });

  it("accepts numeric from/to (budget)", () => {
    const c = DiffChangeSchema.parse({
      field: "budget_monthly_usd",
      from: 10.0,
      to: 25.0,
    });
    expect(c.to).toBe(25.0);
  });
});

// ─── AgentVersionDiffSchema ────────────────────────────────────────────────

describe("AgentVersionDiffSchema", () => {
  it("parses a diff with multiple changes", () => {
    const diff = AgentVersionDiffSchema.parse({
      agent_id: "research",
      from_version: 1,
      to_version: 3,
      changes: [
        { field: "system_prompt", from: "old prompt", to: "new prompt" },
        {
          field: "tools",
          from: ["get_time"],
          to: ["get_time", "quill_finance_summary"],
        },
      ],
    });
    expect(diff.changes).toHaveLength(2);
    expect(diff.from_version).toBe(1);
    expect(diff.to_version).toBe(3);
  });

  it("parses an empty diff (no changes)", () => {
    const diff = AgentVersionDiffSchema.parse({
      agent_id: "ops",
      from_version: 2,
      to_version: 2,
      changes: [],
    });
    expect(diff.changes).toHaveLength(0);
  });
});

// ─── AgentDetailSchema — Phase 5 additive fields ──────────────────────────

describe("AgentDetailSchema (Phase 5 additive)", () => {
  const baseDetail = {
    agent_id: "research",
    system_prompt: "You are a research assistant.",
    model: "claude-fable-5",
    tools: ["get_time"],
    memory_policy: "off",
    budget_monthly_usd: 10.0,
    enabled: true,
    is_seed: false,
    created_at: "2026-07-01T10:00:00+00:00",
  };

  it("still parses without version/published (backward compat)", () => {
    const d = AgentDetailSchema.parse(baseDetail);
    expect(d.version).toBeUndefined();
    expect(d.published).toBeUndefined();
  });

  it("parses with version and published included", () => {
    const d = AgentDetailSchema.parse({ ...baseDetail, version: 3, published: true });
    expect(d.version).toBe(3);
    expect(d.published).toBe(true);
  });
});
