import { describe, it, expect } from "vitest";
import {
  AaceClassificationSchema,
  CostSchedulePackageSchema,
  EstimateStatusSchema,
  EstimateUploadResponseSchema,
  isEstimateInFlight,
} from "../schemas";

/**
 * Phase G.2 schema sanity tests.
 *
 * These exist to lock the boundary between the API and the UI: the upload
 * status envelope must round-trip with the fields the /estimates page reads,
 * and the two new artifact types must parse the canonical agent shapes from
 * agentic-pmo-prompts/schemas/*.schema.json.
 */

describe("EstimateStatusSchema", () => {
  it("parses the canonical /v1/estimates/{id}/status payload", () => {
    const raw = {
      upload_id: "abc123",
      status: "extracting",
      project_label: "QPB1 — DH-2 80% DD",
      notes: "",
      uploaded_files: [
        {
          filename: "DH-2-A100.pdf",
          kind: "pdf",
          size_bytes: 4_200_000,
          extraction_status: "ok",
          extraction_summary: "12 pages, 2 title blocks, 4 detail callouts",
          minio_key: "estimates/abc123/raw/DH-2-A100.pdf",
        },
      ],
      classification_artifact_id: null,
      package_artifact_id: null,
      created_at: "2026-05-09T03:00:00Z",
      updated_at: "2026-05-09T03:00:30Z",
      error_message: null,
    };
    const parsed = EstimateStatusSchema.parse(raw);
    expect(parsed.upload_id).toBe("abc123");
    expect(parsed.status).toBe("extracting");
    expect(parsed.uploaded_files[0].kind).toBe("pdf");
  });

  it("tolerates forward-compat extra fields (passthrough)", () => {
    const raw = {
      upload_id: "x",
      status: "queued",
      project_label: "",
      notes: "",
      uploaded_files: [],
      created_at: "2026-05-09T00:00:00Z",
      updated_at: "2026-05-09T00:00:00Z",
      future_field: { anything: 1 },
    };
    expect(() => EstimateStatusSchema.parse(raw)).not.toThrow();
  });

  it("accepts unknown status strings via the union fallback", () => {
    const raw = {
      upload_id: "x",
      status: "transitional_state_we_havent_seen_yet",
      project_label: "",
      notes: "",
      uploaded_files: [],
      created_at: "2026-05-09T00:00:00Z",
      updated_at: "2026-05-09T00:00:00Z",
    };
    expect(() => EstimateStatusSchema.parse(raw)).not.toThrow();
  });
});

describe("EstimateUploadResponseSchema", () => {
  it("parses the upload response envelope", () => {
    const raw = {
      upload_id: "u1",
      file_count: 3,
      total_bytes: 15_000_000,
      extraction_started: true,
    };
    const parsed = EstimateUploadResponseSchema.parse(raw);
    expect(parsed.upload_id).toBe("u1");
    expect(parsed.file_count).toBe(3);
  });
});

describe("AaceClassificationSchema", () => {
  it("parses a Class 4 classification artifact", () => {
    const raw = {
      artifact_type: "aace_classification",
      artifact_id: "cls-1",
      title: "Class 4 classification — QPB1",
      summary: "DD set supports a Class 4 estimate.",
      body_markdown: "# Classification\n\nThe set supports Class 4.",
      metadata: {
        project_label: "QPB1",
        class: "4",
        design_maturity_estimate_pct: 12,
        accuracy_range: { low_pct: -30, high_pct: 50 },
        supporting_evidence: [
          {
            category: "scope_completeness",
            score: 0.65,
            evidence: "All 4 buildings have a floor-plan footprint.",
          },
        ],
        missing_for_next_class: [
          {
            deliverable: "Equipment schedule",
            rationale: "Needed for direct cost rolldown.",
            would_unlock_class: "3",
          },
        ],
        uploaded_files: [
          {
            filename: "x.pdf",
            kind: "pdf",
            size_bytes: 1024,
            extraction_status: "ok",
          },
        ],
      },
      citations: [],
      confidence: 0.74,
    };
    const parsed = AaceClassificationSchema.parse(raw);
    expect(parsed.metadata.class).toBe("4");
    expect(parsed.metadata.supporting_evidence[0].score).toBe(0.65);
  });
});

describe("CostSchedulePackageSchema", () => {
  it("parses a minimal cost_schedule_package shape", () => {
    const raw = {
      artifact_type: "cost_schedule_package",
      artifact_id: "pkg-1",
      title: "Class 4 estimate — QPB1",
      summary: "Class 4 / Level 2",
      body_markdown: "# Package",
      metadata: {
        project_label: "QPB1",
        aace_class: "4",
        schedule_level: 2,
        currency: "USD",
        base_year: "2026",
        estimate: {
          rows: [
            {
              csi_section: "26 13 13",
              description: "MV Switchgear, 15kV",
              quantity: 4,
              unit: "EA",
              unit_rate_usd: 285_000,
              extended_usd: 1_140_000,
              rate_source: "library_v0_1",
              confidence: 0.75,
            },
          ],
          subtotal_direct_usd: 1_140_000,
          indirects: [],
          contingency: {
            pct_of_direct_plus_indirect: 25,
            amount_usd: 285_000,
            rationale: "Class 4 band — see basis.",
          },
          total_usd: 1_425_000,
        },
        schedule: {
          level: 2,
          activities: [
            {
              id: "A1",
              name: "Site mobilization",
              duration_days: 14,
            },
            {
              id: "A2",
              name: "MV switchgear procurement",
              duration_days: 120,
              predecessors: [{ id: "A1", type: "FS", lag_days: 0 }],
            },
          ],
          total_duration_days: 134,
        },
        basis_of_estimate: "Library rates + LLM benchmarks for missing rows.",
        basis_of_schedule: "Long-lead MV switchgear drives critical path.",
        risk_register: [
          {
            id: "R1",
            description: "OEM lead time slip",
            category: "supply_chain",
            likelihood: "medium",
            impact_usd_low: 0,
            impact_usd_high: 50_000,
            schedule_impact_days_low: 0,
            schedule_impact_days_high: 30,
          },
        ],
        missing_info_to_next_class: [
          {
            deliverable: "Equipment schedule with model numbers",
            rationale: "Lets us swap LLM rates for vendor quotes.",
            would_unlock_class: "3",
            estimated_cost_to_complete_usd: 25_000,
          },
        ],
        uploaded_files: [
          {
            filename: "x.pdf",
            kind: "pdf",
            size_bytes: 1024,
            extraction_status: "ok",
          },
        ],
        library_version: "v0.1.0",
      },
      citations: [],
      confidence: 0.7,
    };
    const parsed = CostSchedulePackageSchema.parse(raw);
    expect(parsed.metadata.aace_class).toBe("4");
    expect(parsed.metadata.estimate.rows[0].extended_usd).toBe(1_140_000);
    expect(parsed.metadata.schedule.activities.length).toBe(2);
    expect(parsed.metadata.risk_register[0].likelihood).toBe("medium");
  });
});

describe("isEstimateInFlight", () => {
  it("returns true while the run hasn't published or failed", () => {
    expect(isEstimateInFlight("queued")).toBe(true);
    expect(isEstimateInFlight("extracting")).toBe(true);
    expect(isEstimateInFlight("classifying")).toBe(true);
    expect(isEstimateInFlight("awaiting_classification_approval")).toBe(true);
    expect(isEstimateInFlight("estimating")).toBe(true);
    expect(isEstimateInFlight("awaiting_package_approval")).toBe(true);
  });
  it("returns false on terminal states", () => {
    expect(isEstimateInFlight("done")).toBe(false);
    expect(isEstimateInFlight("failed")).toBe(false);
    expect(isEstimateInFlight(undefined)).toBe(false);
  });
});
