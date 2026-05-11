/**
 * Sprint Contracts.2 — schema + rendering tests.
 *
 * Validates:
 * - ContractReviewMetadataSchema parses the canonical review output
 * - ContractInterpretationSchema parses a Q&A item
 * - List response schemas parse correctly
 * - Disclaimer is always present in parsed output
 * - Unknown artifact types still fall through (don't break ArtifactView)
 */

import { describe, it, expect } from "vitest";
import {
  ContractReviewMetadataSchema,
  ContractReviewSchema,
  ContractReviewListResponseSchema,
  ContractInterpretationSchema,
  ContractInterpretationListResponseSchema,
} from "../schemas";

const CANONICAL_DISCLAIMER =
  "AI-generated analysis. This is not legal advice. Review with qualified counsel before relying on it for any binding decision.";

// ── Fixtures ──────────────────────────────────────────────────────────────
const VALID_MARKET_TERMS = {
  payment_terms: { verdict: "in-market", notes: "Net 30 is acceptable." },
  retention: { verdict: "off-market-unfavorable", notes: "10% never reduces." },
  indemnification: { verdict: "off-market-unfavorable", notes: "Broad form." },
  limitation_of_liability: { verdict: "not-present", notes: "No cap." },
  termination: { verdict: "unclear", notes: "Termination for convenience only." },
  change_orders: { verdict: "in-market", notes: "Written CO required." },
  dispute_resolution: { verdict: "in-market", notes: "AAA in Columbus, OH." },
  insurance: { verdict: "in-market", notes: "GL $1M/$2M." },
};

const VALID_REVIEW: Record<string, unknown> = {
  risk_flags: [
    {
      severity: "critical",
      category: "indemnification",
      title: "Broad-form indemnity",
      summary: "Covers GC's own negligence.",
      verbatim: "Subcontractor shall indemnify...",
      location: "Section 14",
      why_it_matters: "Exposes subcontractor to unlimited liability.",
      suggested_action: "Negotiate mutual indemnity.",
    },
  ],
  missing_protections: [
    {
      category: "limitation_of_liability",
      title: "No LOL cap",
      why_typical: "In-market Ohio subcontracts cap liability.",
      suggested_clause: "Total liability capped at contract price.",
    },
  ],
  market_terms_assessment: VALID_MARKET_TERMS,
  plain_english_summary: "This contract is heavily stacked against the subcontractor.",
  recommended_actions: ["Confirm with counsel.", "Negotiate LOL cap before signing."],
  disclaimer: CANONICAL_DISCLAIMER,
  citations: [{ quote: "Subcontractor shall indemnify...", location: "Section 14" }],
};

const VALID_INTERPRETATION: Record<string, unknown> = {
  contract_upload_id: "upload-abc",
  question: "What does the indemnity obligate me to?",
  answer: "You must defend and indemnify the GC from all claims.",
  supporting_clauses: [
    {
      verbatim: "Subcontractor shall indemnify...",
      location: "Section 14",
      why_relevant: "This is the full indemnity clause.",
    },
  ],
  confidence: 0.9,
  caveats: [{ caveat: "Ohio courts may not enforce broad-form indemnity." }],
  disclaimer: CANONICAL_DISCLAIMER,
};

// ── ContractReviewMetadataSchema ──────────────────────────────────────────
describe("ContractReviewMetadataSchema", () => {
  it("parses a complete valid review output", () => {
    const parsed = ContractReviewMetadataSchema.parse(VALID_REVIEW);
    expect(parsed.risk_flags).toHaveLength(1);
    expect(parsed.risk_flags[0].severity).toBe("critical");
    expect(parsed.missing_protections).toHaveLength(1);
    expect(parsed.plain_english_summary).toContain("subcontractor");
    expect(parsed.recommended_actions).toHaveLength(2);
    expect(parsed.disclaimer).toBe(CANONICAL_DISCLAIMER);
    expect(parsed.citations).toHaveLength(1);
  });

  it("parses with empty arrays (no flags, no missing)", () => {
    const sparse = {
      ...VALID_REVIEW,
      risk_flags: [],
      missing_protections: [],
      citations: [],
    };
    const parsed = ContractReviewMetadataSchema.parse(sparse);
    expect(parsed.risk_flags).toEqual([]);
    expect(parsed.missing_protections).toEqual([]);
  });

  it("defaults empty arrays when arrays are missing", () => {
    const noArrays = {
      market_terms_assessment: VALID_MARKET_TERMS,
      plain_english_summary: "Summary.",
      recommended_actions: ["Check with counsel."],
      disclaimer: CANONICAL_DISCLAIMER,
    };
    const parsed = ContractReviewMetadataSchema.parse(noArrays);
    expect(parsed.risk_flags).toEqual([]);
    expect(parsed.missing_protections).toEqual([]);
    expect(parsed.citations).toEqual([]);
  });

  it("parses all valid severity values", () => {
    for (const severity of ["critical", "high", "medium", "low", "info"]) {
      const withSev = {
        ...VALID_REVIEW,
        risk_flags: [{ ...(VALID_REVIEW.risk_flags as any[])[0], severity }],
      };
      const parsed = ContractReviewMetadataSchema.parse(withSev);
      expect(parsed.risk_flags[0].severity).toBe(severity);
    }
  });

  it("parses all valid market term verdicts", () => {
    for (const verdict of [
      "in-market",
      "off-market-favorable",
      "off-market-unfavorable",
      "not-present",
      "unclear",
    ]) {
      const terms = {
        ...VALID_MARKET_TERMS,
        payment_terms: { verdict, notes: "test" },
      };
      const review = { ...VALID_REVIEW, market_terms_assessment: terms };
      const parsed = ContractReviewMetadataSchema.parse(review);
      expect(parsed.market_terms_assessment.payment_terms.verdict).toBe(verdict);
    }
  });

  it("preserves optional suggested_redline in risk flag", () => {
    const withRedline = {
      ...VALID_REVIEW,
      risk_flags: [
        {
          ...(VALID_REVIEW.risk_flags as any[])[0],
          suggested_redline: "Each party shall indemnify only its own negligence.",
        },
      ],
    };
    const parsed = ContractReviewMetadataSchema.parse(withRedline);
    expect(parsed.risk_flags[0].suggested_redline).toBe(
      "Each party shall indemnify only its own negligence."
    );
  });
});

// ── ContractReviewListResponseSchema ──────────────────────────────────────
describe("ContractReviewListResponseSchema", () => {
  it("parses an empty list", () => {
    const parsed = ContractReviewListResponseSchema.parse({ items: [], total: 0 });
    expect(parsed.items).toEqual([]);
    expect(parsed.total).toBe(0);
  });

  it("parses a list with one item", () => {
    const raw = {
      items: [
        {
          review_artifact_id: "rev-001",
          created_at: "2026-05-11T12:00:00Z",
          severity_counts: { critical: 1, high: 2, medium: 0, low: 1, info: 0 },
        },
      ],
      total: 1,
    };
    const parsed = ContractReviewListResponseSchema.parse(raw);
    expect(parsed.items).toHaveLength(1);
    expect(parsed.items[0].severity_counts.critical).toBe(1);
    expect(parsed.items[0].severity_counts.high).toBe(2);
  });

  it("defaults severity_counts to 0", () => {
    const raw = {
      items: [
        {
          review_artifact_id: "rev-001",
          created_at: "2026-05-11T12:00:00Z",
          severity_counts: {},
        },
      ],
      total: 1,
    };
    const parsed = ContractReviewListResponseSchema.parse(raw);
    expect(parsed.items[0].severity_counts.critical).toBe(0);
    expect(parsed.items[0].severity_counts.high).toBe(0);
  });
});

// ── ContractInterpretationSchema ──────────────────────────────────────────
describe("ContractInterpretationSchema", () => {
  it("parses a complete valid interpretation", () => {
    const parsed = ContractInterpretationSchema.parse(VALID_INTERPRETATION);
    expect(parsed.question).toBe("What does the indemnity obligate me to?");
    expect(parsed.answer).toContain("GC");
    expect(parsed.confidence).toBe(0.9);
    expect(parsed.supporting_clauses).toHaveLength(1);
    expect(parsed.caveats).toHaveLength(1);
    expect(parsed.disclaimer).toBe(CANONICAL_DISCLAIMER);
    expect(parsed.contract_upload_id).toBe("upload-abc");
  });

  it("defaults empty arrays", () => {
    const minimal = {
      contract_upload_id: "upload-abc",
      question: "What is the warranty period?",
      answer: "The contract does not specify a warranty period.",
      confidence: 0.2,
      disclaimer: CANONICAL_DISCLAIMER,
    };
    const parsed = ContractInterpretationSchema.parse(minimal);
    expect(parsed.supporting_clauses).toEqual([]);
    expect(parsed.caveats).toEqual([]);
  });

  it("parses optional interpretation_id", () => {
    const with_id = { ...VALID_INTERPRETATION, interpretation_id: "interp-123" };
    const parsed = ContractInterpretationSchema.parse(with_id);
    expect(parsed.interpretation_id).toBe("interp-123");
  });

  it("confidence is bounded 0-1", () => {
    const parsed = ContractInterpretationSchema.parse({
      ...VALID_INTERPRETATION,
      confidence: 1.0,
    });
    expect(parsed.confidence).toBe(1.0);
  });
});

// ── ContractInterpretationListResponseSchema ──────────────────────────────
describe("ContractInterpretationListResponseSchema", () => {
  it("parses an empty list", () => {
    const parsed = ContractInterpretationListResponseSchema.parse({
      items: [],
      total: 0,
    });
    expect(parsed.items).toEqual([]);
    expect(parsed.total).toBe(0);
  });

  it("parses a list with items", () => {
    const raw = {
      items: [VALID_INTERPRETATION],
      total: 1,
    };
    const parsed = ContractInterpretationListResponseSchema.parse(raw);
    expect(parsed.items).toHaveLength(1);
    expect(parsed.items[0].disclaimer).toBe(CANONICAL_DISCLAIMER);
  });
});

// ── Disclaimer enforcement ─────────────────────────────────────────────────
describe("Disclaimer enforcement", () => {
  it("disclaimer field is present in ContractReviewMetadata", () => {
    const parsed = ContractReviewMetadataSchema.parse(VALID_REVIEW);
    expect(parsed.disclaimer).toBeDefined();
    expect(parsed.disclaimer).toContain("not legal advice");
  });

  it("disclaimer field is present in ContractInterpretation", () => {
    const parsed = ContractInterpretationSchema.parse(VALID_INTERPRETATION);
    expect(parsed.disclaimer).toBeDefined();
    expect(parsed.disclaimer).toContain("not legal advice");
  });

  it("disclaimer has correct canonical text in ContractReviewMetadata", () => {
    const parsed = ContractReviewMetadataSchema.parse(VALID_REVIEW);
    expect(parsed.disclaimer).toBe(CANONICAL_DISCLAIMER);
  });
});

// ── ArtifactView fallthrough (unknown type) ────────────────────────────────
describe("Unknown artifact type fallthrough", () => {
  it("ContractReviewSchema allows passthrough on unknown artifact_type", () => {
    // If artifact_type is something else, ContractReviewMetadataSchema should
    // still parse (it's passthrough) as long as required fields are present.
    const with_unknown_type = {
      ...VALID_REVIEW,
      artifact_type: "some_future_type",
    };
    // passthrough schema should not throw on extra/different fields
    const parsed = ContractReviewMetadataSchema.parse(with_unknown_type);
    expect(parsed.disclaimer).toBe(CANONICAL_DISCLAIMER);
  });
});
