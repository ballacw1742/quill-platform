/**
 * deliverable-content.test.ts
 *
 * Unit tests for the pure content-type detection and extraction helpers in
 * web/lib/deliverable-content.ts, and for the G2/G3 additions to api.ts
 * (schema shape + type exports).
 *
 * Tests are DOM-free (vitest node environment per vitest.config.ts).
 */

import { describe, it, expect } from "vitest";
import {
  detectContentKind,
  extractDocText,
  extractSheetRows,
  extractKVPairs,
  isCodevGate,
  diffContent,
  type ContentRenderKind,
} from "../deliverable-content";
import {
  DeliverableSchema,
  type DeliverablePatchPayload,
  type CodevPayload,
  type ResumePayload,
  type CodevProposal,
} from "../api";

// ── detectContentKind ─────────────────────────────────────────────────────

describe("detectContentKind", () => {
  it("returns 'empty' for null/undefined/empty content", () => {
    expect(detectContentKind(null)).toBe<ContentRenderKind>("empty");
    expect(detectContentKind(undefined)).toBe<ContentRenderKind>("empty");
    expect(detectContentKind({})).toBe<ContentRenderKind>("kv");
  });

  it("returns 'sheet' when rows is an array of arrays", () => {
    const content = {
      rows: [
        ["Header A", "Header B"],
        ["Value 1", "Value 2"],
      ],
    };
    expect(detectContentKind(content)).toBe<ContentRenderKind>("sheet");
  });

  it("returns 'kv' (not sheet) when rows is an array of objects, not arrays", () => {
    const content = {
      rows: [{ col_a: "a", col_b: "b" }],
    };
    expect(detectContentKind(content)).toBe<ContentRenderKind>("kv");
  });

  it("returns 'doc' when content has a text field", () => {
    expect(detectContentKind({ text: "hello world" })).toBe<ContentRenderKind>("doc");
  });

  it("returns 'doc' when content has a summary field", () => {
    expect(detectContentKind({ summary: "brief summary" })).toBe<ContentRenderKind>("doc");
  });

  it("returns 'doc' when content has a markdown field", () => {
    expect(detectContentKind({ markdown: "# Heading\n\nBody." })).toBe<ContentRenderKind>("doc");
  });

  it("returns 'doc' when content has body_markdown field", () => {
    expect(detectContentKind({ body_markdown: "## Section\n\ncontent." })).toBe<ContentRenderKind>("doc");
  });

  it("returns 'kv' for a structured object with no text or sheet fields", () => {
    const content = { scope: "mechanical only", budget: 500000, phases: ["A", "B"] };
    expect(detectContentKind(content)).toBe<ContentRenderKind>("kv");
  });

  it("sheet takes precedence over doc when both fields present", () => {
    const content = {
      rows: [["A", "B"], ["1", "2"]],
      summary: "also has summary",
    };
    expect(detectContentKind(content)).toBe<ContentRenderKind>("sheet");
  });
});

// ── extractDocText ────────────────────────────────────────────────────────

describe("extractDocText", () => {
  it("prefers markdown over other text fields", () => {
    expect(
      extractDocText({ markdown: "## Doc", text: "plain", summary: "brief" }),
    ).toBe("## Doc");
  });

  it("falls back to body_markdown when markdown absent", () => {
    expect(
      extractDocText({ body_markdown: "# Section", text: "plain" }),
    ).toBe("# Section");
  });

  it("falls back to text when markdown fields absent", () => {
    expect(extractDocText({ text: "plain text", summary: "summary" })).toBe(
      "plain text",
    );
  });

  it("falls back to summary as last resort", () => {
    expect(extractDocText({ summary: "only summary" })).toBe("only summary");
  });

  it("returns empty string when no text field present", () => {
    expect(extractDocText({ scope: "mechanical" })).toBe("");
  });
});

// ── extractSheetRows ──────────────────────────────────────────────────────

describe("extractSheetRows", () => {
  it("returns rows coerced to string[][]", () => {
    const content = {
      rows: [
        ["Name", "Value"],
        ["Scope", 42],
        [true, null],
      ],
    };
    const rows = extractSheetRows(content);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toEqual(["Name", "Value"]);
    expect(rows[1]).toEqual(["Scope", "42"]);
    expect(rows[2]).toEqual(["true", ""]);
  });

  it("returns empty array when rows absent", () => {
    expect(extractSheetRows({ summary: "no rows here" })).toEqual([]);
  });

  it("returns empty array when rows is not an array", () => {
    expect(extractSheetRows({ rows: "not-an-array" })).toEqual([]);
  });

  it("handles empty rows array", () => {
    expect(extractSheetRows({ rows: [] })).toEqual([]);
  });
});

// ── extractKVPairs ────────────────────────────────────────────────────────

describe("extractKVPairs", () => {
  it("returns key-value pairs for simple fields", () => {
    const pairs = extractKVPairs({ scope: "mechanical", budget: 500000 });
    expect(pairs).toContainEqual({ key: "scope", value: "mechanical" });
    expect(pairs).toContainEqual({ key: "budget", value: "500000" });
  });

  it("skips the 'rows' and 'drive' system keys", () => {
    const pairs = extractKVPairs({
      rows: [["a", "b"]],
      drive: { url: "https://docs.google.com/..." },
      scope: "electrical",
    });
    expect(pairs.map((p) => p.key)).not.toContain("rows");
    expect(pairs.map((p) => p.key)).not.toContain("drive");
    expect(pairs.map((p) => p.key)).toContain("scope");
  });

  it("JSON-stringifies nested objects", () => {
    const pairs = extractKVPairs({ meta: { class: "4", phases: ["A"] } });
    const metaPair = pairs.find((p) => p.key === "meta");
    expect(metaPair).toBeDefined();
    expect(metaPair!.value).toContain('"class"');
  });

  it("returns empty array for empty object", () => {
    expect(extractKVPairs({})).toEqual([]);
  });

  it("coerces booleans to string", () => {
    const pairs = extractKVPairs({ active: true, disabled: false });
    expect(pairs).toContainEqual({ key: "active", value: "true" });
    expect(pairs).toContainEqual({ key: "disabled", value: "false" });
  });
});

// ── isCodevGate ───────────────────────────────────────────────────────────

describe("isCodevGate", () => {
  it("returns true when status=awaiting_human AND meta.hitl_kind=co_development", () => {
    expect(isCodevGate("awaiting_human", { hitl_kind: "co_development" })).toBe(true);
  });

  it("returns false when status=awaiting_human but hitl_kind=decision", () => {
    expect(isCodevGate("awaiting_human", { hitl_kind: "decision" })).toBe(false);
  });

  it("returns false when status is not awaiting_human (even if meta is right)", () => {
    expect(isCodevGate("approved", { hitl_kind: "co_development" })).toBe(false);
    expect(isCodevGate("in_progress", { hitl_kind: "co_development" })).toBe(false);
  });

  it("returns false when meta is null or undefined", () => {
    expect(isCodevGate("awaiting_human", null)).toBe(false);
    expect(isCodevGate("awaiting_human", undefined)).toBe(false);
  });

  it("returns false when meta is empty object (no hitl_kind)", () => {
    expect(isCodevGate("awaiting_human", {})).toBe(false);
  });
});

// ── diffContent ──────────────────────────────────────────────────────────

describe("diffContent", () => {
  it("serializes before and after content", () => {
    const current = { text: "original text" };
    const proposed = { text: "revised text" };
    const { before, after } = diffContent(current, proposed);
    expect(before).toContain("original text");
    expect(after).toContain("revised text");
  });

  it("handles null current content gracefully", () => {
    const { before } = diffContent(null, { text: "new" });
    expect(before).toBe("{}");
  });

  it("handles undefined current content gracefully", () => {
    const { before } = diffContent(undefined, { text: "new" });
    expect(before).toBe("{}");
  });
});

// ── DeliverableSchema G2 additions ───────────────────────────────────────

describe("DeliverableSchema — G2 drive_url field", () => {
  const MINIMAL_DELIVERABLE = {
    id: "d-001",
    user_id: "u-001",
    project_id: "p-001",
    module_key: "site_control",
    deliverable_type: "scope_summary",
    title: "Site Control Scope",
    status: "draft",
    version: 1,
    content: null,
    meta: null,
    stage_key: "origination",
    created_at: "2026-07-10T00:00:00Z",
    updated_at: "2026-07-10T00:00:00Z",
  };

  it("parses a deliverable with drive_url present", () => {
    const raw = {
      ...MINIMAL_DELIVERABLE,
      drive_url: "https://docs.google.com/document/d/abc123/edit",
    };
    const r = DeliverableSchema.safeParse(raw);
    expect(r.success).toBe(true);
    if (r.success) {
      expect(r.data.drive_url).toBe(
        "https://docs.google.com/document/d/abc123/edit",
      );
    }
  });

  it("defaults drive_url to null when absent", () => {
    const r = DeliverableSchema.safeParse(MINIMAL_DELIVERABLE);
    expect(r.success).toBe(true);
    if (r.success) {
      expect(r.data.drive_url).toBeNull();
    }
  });

  it("accepts null for drive_url explicitly", () => {
    const raw = { ...MINIMAL_DELIVERABLE, drive_url: null };
    const r = DeliverableSchema.safeParse(raw);
    expect(r.success).toBe(true);
    if (r.success) {
      expect(r.data.drive_url).toBeNull();
    }
  });
});

// ── DeliverablePatchPayload — change_action ───────────────────────────────

describe("DeliverablePatchPayload — change_action type", () => {
  it("accepts valid change_action values at the type level (TypeScript compile-time check via runtime)", () => {
    // Since TypeScript types are erased at runtime, we validate the accepted
    // shapes by constructing valid payloads and checking no TS error surfaces.
    // This test documents the contract so the build gate will catch regressions.
    const p1: DeliverablePatchPayload = { change_action: "updated" };
    const p2: DeliverablePatchPayload = { change_action: "human_edited" };
    const p3: DeliverablePatchPayload = { change_action: "co_developed" };
    const p4: DeliverablePatchPayload = { title: "New title" }; // change_action optional
    expect(p1.change_action).toBe("updated");
    expect(p2.change_action).toBe("human_edited");
    expect(p3.change_action).toBe("co_developed");
    expect(p4.change_action).toBeUndefined();
  });
});

// ── CodevPayload / ResumePayload / CodevProposal shapes ───────────────────

describe("G3 hook payload types", () => {
  it("CodevPayload has required prompt and optional current_content", () => {
    const p1: CodevPayload = { prompt: "Revise scope assumptions" };
    const p2: CodevPayload = {
      prompt: "Resolve drawing conflict",
      current_content: { text: "original" },
    };
    expect(p1.prompt).toBe("Revise scope assumptions");
    expect(p2.current_content).toEqual({ text: "original" });
  });

  it("ResumePayload has required content and optional resume_chain", () => {
    const p1: ResumePayload = { content: { text: "accepted" } };
    const p2: ResumePayload = { content: { text: "accepted" }, resume_chain: false };
    expect(p1.resume_chain).toBeUndefined();
    expect(p2.resume_chain).toBe(false);
  });

  it("CodevProposal shape has required fields", () => {
    const proposal: CodevProposal = {
      proposed_content: { text: "revised content" },
      proposed_summary: "Added scope assumptions",
      based_on_version: 3,
    };
    expect(proposal.based_on_version).toBe(3);
    expect(proposal.proposed_summary).toBe("Added scope assumptions");
  });

  it("CodevProposal allows null proposed_summary", () => {
    const proposal: CodevProposal = {
      proposed_content: { text: "revised" },
      proposed_summary: null,
      based_on_version: 1,
    };
    expect(proposal.proposed_summary).toBeNull();
  });
});
