import { describe, it, expect } from "vitest";
import {
  ContractSchema,
  ContractListPageSchema,
  ContractListItemSchema,
  ContractUploadResponseSchema,
  ContractStatusSchema,
  ContractExtractionMetadataSchema,
  CONTRACT_DISCLAIMER,
} from "../schemas";

/**
 * Sprint Contracts.1 — schema sanity tests.
 *
 * Lock the boundary between the API and the UI: upload response, status,
 * list page, full contract record, and contract extraction metadata must all
 * parse the canonical API shapes.
 */

describe("ContractUploadResponseSchema", () => {
  it("parses the canonical upload response", () => {
    const raw = {
      upload_id: "c-upload-001",
      file_count: 2,
      total_bytes: 500_000,
      extraction_started: true,
    };
    const parsed = ContractUploadResponseSchema.parse(raw);
    expect(parsed.upload_id).toBe("c-upload-001");
    expect(parsed.file_count).toBe(2);
    expect(parsed.extraction_started).toBe(true);
  });

  it("defaults extraction_started to true when missing", () => {
    const parsed = ContractUploadResponseSchema.parse({
      upload_id: "x",
      file_count: 1,
      total_bytes: 1000,
    });
    expect(parsed.extraction_started).toBe(true);
  });
});

describe("ContractStatusSchema", () => {
  it("parses a lightweight status response", () => {
    const raw = {
      upload_id: "c-001",
      status: "extracting",
      contract_type: "subcontract",
      effective_date: null,
      expiration_date: null,
      error_message: null,
      created_at: "2026-05-11T12:00:00Z",
      updated_at: "2026-05-11T12:00:30Z",
    };
    const parsed = ContractStatusSchema.parse(raw);
    expect(parsed.upload_id).toBe("c-001");
    expect(parsed.status).toBe("extracting");
    expect(parsed.contract_type).toBe("subcontract");
  });

  it("accepts unknown status strings (forward compat)", () => {
    const raw = {
      upload_id: "c-002",
      status: "some_future_status",
      created_at: "2026-05-11T12:00:00Z",
      updated_at: "2026-05-11T12:00:00Z",
    };
    expect(() => ContractStatusSchema.parse(raw)).not.toThrow();
  });

  it("accepts all known status values", () => {
    const statuses = [
      "uploaded", "extracting", "extracted",
      "reviewing", "reviewed", "drafting", "drafted", "failed",
    ];
    for (const status of statuses) {
      expect(() =>
        ContractStatusSchema.parse({
          upload_id: "c",
          status,
          created_at: "2026-05-11T00:00:00Z",
          updated_at: "2026-05-11T00:00:00Z",
        }),
      ).not.toThrow();
    }
  });
});

describe("ContractListItemSchema", () => {
  it("parses a list item with all fields", () => {
    const raw = {
      upload_id: "c-list-001",
      project_label: "Riverside Office",
      contract_type: "owner_gc",
      status: "extracted",
      source: "upload",
      effective_date: "2026-03-01",
      expiration_date: "2027-03-01",
      total_value_usd: 3_500_000,
      created_at: "2026-05-01T10:00:00Z",
      updated_at: "2026-05-01T10:05:00Z",
      error_message: null,
    };
    const parsed = ContractListItemSchema.parse(raw);
    expect(parsed.upload_id).toBe("c-list-001");
    expect(parsed.total_value_usd).toBe(3_500_000);
    expect(parsed.contract_type).toBe("owner_gc");
  });

  it("defaults project_label and source when missing", () => {
    const parsed = ContractListItemSchema.parse({
      upload_id: "c",
      status: "uploaded",
      created_at: "2026-05-11T00:00:00Z",
      updated_at: "2026-05-11T00:00:00Z",
    });
    expect(parsed.project_label).toBe("");
    expect(parsed.source).toBe("upload");
  });

  it("accepts all known contract types", () => {
    const types = [
      "owner_gc", "subcontract", "change_order", "purchase_order",
      "letter_of_intent", "nda", "msa", "equipment_lease",
      "insurance_certificate", "lien_waiver", "other", "unknown",
    ];
    for (const ct of types) {
      expect(() =>
        ContractListItemSchema.parse({
          upload_id: "c",
          contract_type: ct,
          status: "uploaded",
          created_at: "2026-05-11T00:00:00Z",
          updated_at: "2026-05-11T00:00:00Z",
        }),
      ).not.toThrow();
    }
  });
});

describe("ContractListPageSchema", () => {
  it("parses a list page envelope", () => {
    const raw = {
      items: [
        {
          upload_id: "c-001",
          project_label: "Project A",
          status: "uploaded",
          created_at: "2026-05-11T00:00:00Z",
          updated_at: "2026-05-11T00:00:00Z",
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    };
    const parsed = ContractListPageSchema.parse(raw);
    expect(parsed.items.length).toBe(1);
    expect(parsed.total).toBe(1);
    expect(parsed.offset).toBe(0);
  });
});

describe("ContractSchema", () => {
  it("parses a full contract record with disclaimer", () => {
    const raw = {
      upload_id: "c-full-001",
      project_label: "Riverside Office",
      contract_type: "subcontract",
      status: "extracted",
      source: "upload",
      uploaded_files: [
        {
          filename: "subcontract.pdf",
          kind: "pdf",
          size_bytes: 120_000,
          extraction_status: "ok",
          extraction_summary: "25 pages, parties and payment terms found",
          minio_key: "contracts/c-full-001/raw/subcontract.pdf",
        },
      ],
      extracted_fields: null,
      parties: [{ role: "Subcontractor", name: "Acme Concrete" }],
      effective_date: "2026-03-15",
      expiration_date: "2026-09-30",
      total_value_usd: 425_000,
      notes: "Concrete scope only",
      error_message: null,
      classification_artifact_id: null,
      review_artifact_id: null,
      created_at: "2026-05-11T12:00:00Z",
      updated_at: "2026-05-11T12:00:05Z",
      disclaimer: CONTRACT_DISCLAIMER,
    };
    const parsed = ContractSchema.parse(raw);
    expect(parsed.upload_id).toBe("c-full-001");
    expect(parsed.disclaimer).toBe(CONTRACT_DISCLAIMER);
    expect(parsed.parties.length).toBe(1);
    expect(parsed.uploaded_files[0].extraction_status).toBe("ok");
    expect(parsed.total_value_usd).toBe(425_000);
  });

  it("requires disclaimer field", () => {
    const raw = {
      upload_id: "c-nodisclaimer",
      status: "uploaded",
      // disclaimer missing — should be required
      created_at: "2026-05-11T00:00:00Z",
      updated_at: "2026-05-11T00:00:00Z",
    };
    expect(() => ContractSchema.parse(raw)).toThrow();
  });

  it("tolerates extra fields (passthrough)", () => {
    expect(() =>
      ContractSchema.parse({
        upload_id: "c",
        status: "uploaded",
        disclaimer: CONTRACT_DISCLAIMER,
        created_at: "2026-05-11T00:00:00Z",
        updated_at: "2026-05-11T00:00:00Z",
        future_field_from_contracts2: { anything: 1 },
      }),
    ).not.toThrow();
  });
});

describe("ContractExtractionMetadataSchema", () => {
  it("parses a full contract_extraction artifact (subcontract example)", () => {
    const raw = {
      artifact_type: "contract_extraction",
      contract_type: "subcontract",
      confidence: 0.97,
      parties: [
        {
          role: "General Contractor",
          name: "Monark Construction LLC",
          address: "1234 Industrial Pkwy, Columbus, OH 43215",
          contact: "Charles Mitchell, President",
        },
        {
          role: "Subcontractor",
          name: "Acme Concrete Works Inc.",
          address: "567 Ready Mix Rd, Westerville, OH 43081",
          contact: "John Smith, President",
        },
      ],
      effective_date: "2026-03-15",
      expiration_date: "2026-09-30",
      total_value_usd: 425000,
      payment_terms: "Monthly progress payments within 30 days of Owner payment",
      payment_schedule: [
        {
          description: "Monthly progress payments",
          amount_usd: null,
          due: "Within 30 days of Contractor receiving payment from Owner",
          condition: "Based on approved Schedule of Values",
        },
      ],
      key_milestones: [
        { description: "Notice to Proceed", date: "2026-04-01" },
        { description: "Substantial completion", date: "2026-09-30" },
      ],
      obligations: {
        "Monark Construction LLC": [
          "Pay Subcontractor monthly progress payments",
          "Issue written Notice to Proceed",
        ],
        "Acme Concrete Works Inc.": [
          "Furnish all labor, materials, equipment",
          "Complete work per drawings",
        ],
      },
      notable_clauses: {
        indemnification: {
          verbatim: "To the fullest extent permitted by law, Subcontractor shall indemnify...",
          paraphrase: "Subcontractor indemnifies Contractor from claims arising from work.",
        },
        termination: null,
        dispute_resolution: null,
        insurance_requirements: null,
        limitation_of_liability: null,
        change_orders: null,
        payment_terms: null,
      },
      notes: "Complete subcontract agreement for concrete work.",
      disclaimer: CONTRACT_DISCLAIMER,
      citations: [
        { quote: "$425,000.00", location: "Article 1, Section 1.1" },
      ],
    };
    const parsed = ContractExtractionMetadataSchema.parse(raw);
    expect(parsed.artifact_type).toBe("contract_extraction");
    expect(parsed.contract_type).toBe("subcontract");
    expect(parsed.confidence).toBe(0.97);
    expect(parsed.parties.length).toBe(2);
    expect(parsed.total_value_usd).toBe(425000);
    expect(parsed.disclaimer).toBe(CONTRACT_DISCLAIMER);
    expect(parsed.citations.length).toBe(1);
  });

  it("parses a change_order artifact", () => {
    const raw = {
      artifact_type: "contract_extraction",
      contract_type: "change_order",
      confidence: 0.99,
      parties: [
        { role: "Owner", name: "Metro Development LLC", address: null, contact: null },
      ],
      effective_date: "2026-05-05",
      expiration_date: "2026-11-15",
      total_value_usd: 34750,
      payment_terms: null,
      payment_schedule: [],
      key_milestones: [{ description: "New substantial completion", date: "2026-11-15" }],
      obligations: {},
      notable_clauses: {
        indemnification: null,
        termination: null,
        dispute_resolution: null,
        insurance_requirements: null,
        limitation_of_liability: null,
        change_orders: {
          verbatim: "Upon execution, this Change Order is incorporated into the Contract.",
          paraphrase: "Change order becomes part of the original contract upon execution.",
        },
        payment_terms: null,
      },
      notes: "Change Order #007.",
      disclaimer: CONTRACT_DISCLAIMER,
      citations: [],
    };
    const parsed = ContractExtractionMetadataSchema.parse(raw);
    expect(parsed.contract_type).toBe("change_order");
    expect(parsed.total_value_usd).toBe(34750);
    expect(parsed.notable_clauses?.change_orders).not.toBeNull();
  });

  it("disclaimer must match canonical text", () => {
    const raw = {
      artifact_type: "contract_extraction",
      contract_type: "unknown",
      confidence: 0,
      parties: [],
      effective_date: null,
      expiration_date: null,
      total_value_usd: null,
      payment_terms: null,
      payment_schedule: [],
      key_milestones: [],
      obligations: {},
      notable_clauses: {},
      notes: "",
      disclaimer: CONTRACT_DISCLAIMER, // correct
      citations: [],
    };
    expect(() => ContractExtractionMetadataSchema.parse(raw)).not.toThrow();
  });
});

describe("CONTRACT_DISCLAIMER", () => {
  it("equals the canonical text", () => {
    expect(CONTRACT_DISCLAIMER).toBe(
      "AI-generated analysis. This is not legal advice. Review with qualified counsel before relying on it for any binding decision.",
    );
  });
});
