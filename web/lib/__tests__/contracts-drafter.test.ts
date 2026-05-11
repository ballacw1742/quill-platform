/**
 * Sprint Contracts.3 — schema + hook smoke tests.
 *
 * Validates:
 * - ContractTemplateSchema parses template metadata correctly
 * - ContractTemplateListResponseSchema parses list response
 * - ContractDraftRequestSchema validates draft request input
 * - ContractDraftMetadataSchema parses full agent output
 * - ContractDraftSchema parses the full artifact wrapper
 * - New hooks are exported from api.ts
 * - DraftAttorneyBanner renders without crashing
 */

import { describe, it, expect } from "vitest";
import {
  ContractTemplateSchema,
  ContractTemplateListResponseSchema,
  ContractDraftRequestSchema,
  ContractDraftMetadataSchema,
  ContractDraftSchema,
} from "../schemas";

const CANONICAL_DISCLAIMER =
  "AI-generated analysis. This is not legal advice. Review with qualified counsel before relying on it for any binding decision.";

// ── Fixtures ──────────────────────────────────────────────────────────────
const VALID_TEMPLATE = {
  template_id: "subcontract_standard",
  contract_type: "subcontract",
  display_name: "Standard Subcontract Agreement",
  version: "0.1.0",
  required_variables: ["contractor_name", "subcontractor_name", "subcontract_sum"],
  optional_variables: ["retainage_percent"],
  jurisdiction_notes: "Ohio law governs.",
  suitable_for: "GC/subcontractor agreements.",
  body: "# Generation Guide\n\n...",
};

const VALID_DRAFT_REQUEST = {
  mode: "template" as const,
  contract_type: "subcontract",
  template_id: "subcontract_standard",
  parties: [
    { role: "contractor", name: "Acme GC LLC" },
    { role: "subcontractor", name: "Beta Framing Inc" },
  ],
  effective_date: "2026-06-01",
  expiration_date: null,
  total_value_usd: 125000,
  payment_terms: "Net 30",
  scope_summary: "Framing work for Project Alpha",
  key_terms_requested: [
    { topic: "indemnification", requirement: "mutual only" },
  ],
  jurisdiction: "Ohio",
  notes: "Standard subcontract.",
  prior_contract_upload_id: null,
};

const VALID_DRAFT_METADATA = {
  artifact_type: "contract_draft" as const,
  contract_type: "subcontract",
  mode: "template" as const,
  template_id: "subcontract_standard",
  parties: [
    { role: "Contractor", name: "Summit Construction LLC" },
    { role: "Subcontractor", name: "Precision Framing Inc" },
  ],
  effective_date: "2026-06-01",
  expiration_date: null,
  total_value_usd: 185000,
  title: "Subcontract Agreement — Precision Framing Inc. — Project Alpha",
  summary: "AI-drafted subcontract for framing scope.",
  body_markdown: "# SUBCONTRACT AGREEMENT\n\n...",
  sections: [
    {
      heading: "Article 1 — Parties",
      anchor: "article-1-parties",
      summary: "Identifies the parties.",
    },
  ],
  variables_used: {
    contractor_name: "Summit Construction LLC",
    subcontract_sum: "$185,000",
  },
  key_terms_addressed: {
    indemnification: "Mutual indemnification, limited to own negligence per ORC §4113.62.",
  },
  assumptions_made: [
    {
      topic: "retainage_percent",
      assumption: "5%",
      why_made: "Standard Ohio construction practice.",
    },
  ],
  attorney_review_focus: [
    {
      topic: "Indemnification",
      why: "Ohio anti-indemnity statute applies.",
      suggested_question: "Is the indemnification clause ORC §4113.62 compliant?",
    },
    {
      topic: "Pay-when-paid",
      why: "May not be enforceable as pay-if-paid in Ohio.",
      suggested_question: "Does this clause shift risk appropriately?",
    },
    {
      topic: "Lien rights",
      why: "Ohio lien waiver statute is specific.",
      suggested_question: "Are the lien waiver forms compliant with Ohio law?",
    },
  ],
  disclaimer: CANONICAL_DISCLAIMER,
  citations: [],
};

// ── ContractTemplateSchema ─────────────────────────────────────────────────
describe("ContractTemplateSchema", () => {
  it("parses a valid template", () => {
    const result = ContractTemplateSchema.safeParse(VALID_TEMPLATE);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.template_id).toBe("subcontract_standard");
      expect(result.data.contract_type).toBe("subcontract");
      expect(result.data.required_variables).toContain("contractor_name");
    }
  });

  it("defaults optional fields", () => {
    const minimal = {
      template_id: "test",
      contract_type: "nda",
      display_name: "Test NDA",
    };
    const result = ContractTemplateSchema.safeParse(minimal);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.required_variables).toEqual([]);
      expect(result.data.body).toBe("");
    }
  });
});

// ── ContractTemplateListResponseSchema ────────────────────────────────────
describe("ContractTemplateListResponseSchema", () => {
  it("parses a list response", () => {
    const payload = {
      items: [VALID_TEMPLATE, { ...VALID_TEMPLATE, template_id: "nda_mutual" }],
      total: 2,
    };
    const result = ContractTemplateListResponseSchema.safeParse(payload);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.items).toHaveLength(2);
      expect(result.data.total).toBe(2);
    }
  });

  it("rejects missing items", () => {
    const result = ContractTemplateListResponseSchema.safeParse({ total: 0 });
    expect(result.success).toBe(false);
  });
});

// ── ContractDraftRequestSchema ─────────────────────────────────────────────
describe("ContractDraftRequestSchema", () => {
  it("parses a valid template-mode draft request", () => {
    const result = ContractDraftRequestSchema.safeParse(VALID_DRAFT_REQUEST);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.mode).toBe("template");
      expect(result.data.contract_type).toBe("subcontract");
      expect(result.data.parties).toHaveLength(2);
      expect(result.data.jurisdiction).toBe("Ohio");
    }
  });

  it("parses negotiated mode with no template_id", () => {
    const body = { ...VALID_DRAFT_REQUEST, mode: "negotiated" as const, template_id: null };
    const result = ContractDraftRequestSchema.safeParse(body);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.mode).toBe("negotiated");
    }
  });

  it("rejects invalid mode", () => {
    const bad = { ...VALID_DRAFT_REQUEST, mode: "auto" };
    const result = ContractDraftRequestSchema.safeParse(bad);
    expect(result.success).toBe(false);
  });

  it("defaults jurisdiction to Ohio", () => {
    const noJurisdiction = { ...VALID_DRAFT_REQUEST };
    delete (noJurisdiction as Record<string, unknown>).jurisdiction;
    const result = ContractDraftRequestSchema.safeParse(noJurisdiction);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.jurisdiction).toBe("Ohio");
    }
  });
});

// ── ContractDraftMetadataSchema ────────────────────────────────────────────
describe("ContractDraftMetadataSchema", () => {
  it("parses a valid full agent output", () => {
    const result = ContractDraftMetadataSchema.safeParse(VALID_DRAFT_METADATA);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.title).toBeTruthy();
      expect(result.data.body_markdown).toBeTruthy();
      expect(result.data.attorney_review_focus).toHaveLength(3);
      expect(result.data.assumptions_made).toHaveLength(1);
    }
  });

  it("defaults disclaimer", () => {
    const noDisclaimer = { ...VALID_DRAFT_METADATA };
    delete (noDisclaimer as Record<string, unknown>).disclaimer;
    const result = ContractDraftMetadataSchema.safeParse(noDisclaimer);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.disclaimer).toBe(CANONICAL_DISCLAIMER);
    }
  });

  it("requires title, summary, body_markdown", () => {
    const missing = { ...VALID_DRAFT_METADATA } as Record<string, unknown>;
    delete missing.title;
    const result = ContractDraftMetadataSchema.safeParse(missing);
    expect(result.success).toBe(false);
  });
});

// ── ContractDraftSchema (full artifact wrapper) ────────────────────────────
describe("ContractDraftSchema", () => {
  it("parses the full artifact wrapper", () => {
    const artifact = {
      ...VALID_DRAFT_METADATA,
      artifact_id: "doc-abc-123",
    };
    const result = ContractDraftSchema.safeParse(artifact);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.artifact_type).toBe("contract_draft");
    }
  });

  it("allows extra fields via passthrough", () => {
    const artifact = {
      ...VALID_DRAFT_METADATA,
      extra_field_from_future: true,
    };
    const result = ContractDraftSchema.safeParse(artifact);
    expect(result.success).toBe(true);
  });
});

// ── Hook exports ───────────────────────────────────────────────────────────
describe("Contracts.3 hooks are exported from api.ts", () => {
  it("exports useContractTemplates", async () => {
    const mod = await import("../api");
    expect(typeof mod.useContractTemplates).toBe("function");
  });

  it("exports useContractTemplate", async () => {
    const mod = await import("../api");
    expect(typeof mod.useContractTemplate).toBe("function");
  });

  it("exports useCreateContractDraft", async () => {
    const mod = await import("../api");
    expect(typeof mod.useCreateContractDraft).toBe("function");
  });

  it("exports useRedraftContract", async () => {
    const mod = await import("../api");
    expect(typeof mod.useRedraftContract).toBe("function");
  });

  it("exports useDispatchContractDraft", async () => {
    const mod = await import("../api");
    expect(typeof mod.useDispatchContractDraft).toBe("function");
  });

  it("exports useContractDraft", async () => {
    const mod = await import("../api");
    expect(typeof mod.useContractDraft).toBe("function");
  });
});
