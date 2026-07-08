/**
 * Agent Builder client tests — Phase C (agent-cloud/AGENT_BUILDER.md).
 * Pure-function coverage: draft validation (slug/prompt-cap/budget-vs-cap),
 * and schema validation of the catalog / templates / detail contract shapes.
 */
import { describe, expect, it } from "vitest";

import {
  AgentDetailSchema,
  CatalogSchema,
  SLUG_RE,
  TemplateListSchema,
  validateAgentDraft,
} from "@/lib/agent-cloud";

describe("SLUG_RE", () => {
  it("accepts valid slugs", () => {
    for (const s of ["research", "ops-analyst", "a", "a1", "x-y-z"]) {
      expect(SLUG_RE.test(s)).toBe(true);
    }
  });
  it("rejects invalid slugs", () => {
    for (const s of ["Bad", "-lead", "trail-", "UPPER", "a_b", "a b", ""]) {
      expect(SLUG_RE.test(s)).toBe(false);
    }
  });
});

describe("validateAgentDraft", () => {
  const base = { agent_id: "research", system_prompt: "hi", budget_monthly_usd: 5 };

  it("passes a good draft", () => {
    expect(
      validateAgentDraft(base, { tenantCap: 10, isEdit: false }),
    ).toBeNull();
  });

  it("rejects a bad slug on create", () => {
    expect(
      validateAgentDraft({ ...base, agent_id: "BAD" }, { tenantCap: 10, isEdit: false }),
    ).toMatch(/slug/i);
  });

  it("skips slug check when editing (slug immutable)", () => {
    // even a would-be-invalid slug is ignored on edit
    expect(
      validateAgentDraft({ ...base, agent_id: "personal" }, { tenantCap: 10, isEdit: true }),
    ).toBeNull();
  });

  it("rejects an empty prompt", () => {
    expect(
      validateAgentDraft({ ...base, system_prompt: "   " }, { tenantCap: 10, isEdit: false }),
    ).toMatch(/prompt/i);
  });

  it("rejects a prompt over the cap", () => {
    expect(
      validateAgentDraft(
        { ...base, system_prompt: "x".repeat(20) },
        { tenantCap: 10, isEdit: false, promptCap: 10 },
      ),
    ).toMatch(/limit/i);
  });

  it("rejects a non-positive budget", () => {
    expect(
      validateAgentDraft({ ...base, budget_monthly_usd: 0 }, { tenantCap: 10, isEdit: false }),
    ).toMatch(/budget/i);
  });

  it("rejects a budget over the tenant cap", () => {
    expect(
      validateAgentDraft({ ...base, budget_monthly_usd: 50 }, { tenantCap: 10, isEdit: false }),
    ).toMatch(/cap/i);
  });
});

describe("contract schemas", () => {
  it("parses the catalog shape", () => {
    const catalog = CatalogSchema.parse({
      groups: [
        {
          group: "write",
          label: "Quill writes",
          tools: [
            {
              name: "quill_project_update",
              label: "Update project",
              description: "Propose an update.",
              approval_gated: true,
              memory_tool: false,
            },
          ],
        },
      ],
      models: ["claude-fable-5"],
      memory_policies: ["off", "tools_only", "auto_recall"],
    });
    expect(catalog.groups[0].tools[0].approval_gated).toBe(true);
  });

  it("parses the templates shape", () => {
    const list = TemplateListSchema.parse({
      templates: [
        {
          template_id: "research-assistant",
          name: "Research Assistant",
          summary: "Read-only.",
          system_prompt: "p",
          model: "claude-fable-5",
          tools: ["get_time"],
          memory_policy: "off",
          budget_monthly_usd: 10,
        },
      ],
    });
    expect(list.templates).toHaveLength(1);
  });

  it("parses an agent detail (with is_seed + tools)", () => {
    const d = AgentDetailSchema.parse({
      agent_id: "personal",
      system_prompt: "p",
      model: "claude-fable-5",
      tools: ["get_time", "memory_save"],
      memory_policy: "auto_recall",
      budget_monthly_usd: 20,
      enabled: true,
      is_seed: true,
      created_at: "2026-07-07T12:00:00+00:00",
    });
    expect(d.is_seed).toBe(true);
    expect(d.tools).toContain("memory_save");
  });
});
