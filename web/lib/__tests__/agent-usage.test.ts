/**
 * Usage/meters client tests — Phase E (agent-cloud/LIMITS.md §2).
 * Pure-function + schema coverage for the usage dashboard: budget-fraction
 * math (incl. divide-by-zero + clamping), USD formatting precision, the
 * honest posture label, and validation of the contract shape.
 */
import { describe, expect, it } from "vitest";

import {
  UsageReportSchema,
  budgetPostureLabel,
  fmtUsd,
  spendFraction,
  type UsageTenant,
} from "@/lib/agent-cloud";

describe("spendFraction", () => {
  it("computes the ratio", () => {
    expect(spendFraction(5, 10)).toBe(0.5);
  });
  it("clamps above 1 (over-cap spend)", () => {
    expect(spendFraction(15, 10)).toBe(1);
  });
  it("returns 0 for a zero budget (no divide-by-zero)", () => {
    expect(spendFraction(5, 0)).toBe(0);
  });
  it("returns 0 for a negative or absurd input", () => {
    expect(spendFraction(-1, 10)).toBe(0);
  });
});

describe("fmtUsd", () => {
  it("shows two decimals for normal amounts", () => {
    expect(fmtUsd(8.765433)).toBe("$8.77");
  });
  it("shows four decimals for sub-cent spend so it isn't $0.00", () => {
    expect(fmtUsd(0.0003)).toBe("$0.0003");
  });
  it("shows exactly $0.00 for zero", () => {
    expect(fmtUsd(0)).toBe("$0.00");
  });
});

function tenant(over: Partial<UsageTenant>): UsageTenant {
  return {
    budget_monthly_usd: 10,
    budget_source: "default",
    spend_usd: 0,
    remaining_usd: 10,
    input_tokens: 0,
    output_tokens: 0,
    requests: 0,
    exhausted: false,
    ...over,
  };
}

describe("budgetPostureLabel", () => {
  it("healthy under 50%", () => {
    expect(budgetPostureLabel(tenant({ spend_usd: 1 }))).toBe("Healthy");
  });
  it("flags over half", () => {
    expect(budgetPostureLabel(tenant({ spend_usd: 6 }))).toMatch(/half/i);
  });
  it("flags near cap", () => {
    expect(budgetPostureLabel(tenant({ spend_usd: 9.5 }))).toMatch(/near/i);
  });
  it("flags exhausted regardless of fraction", () => {
    expect(budgetPostureLabel(tenant({ spend_usd: 10, exhausted: true }))).toMatch(
      /exhaust/i,
    );
  });
});

describe("UsageReportSchema", () => {
  it("parses a well-formed report (LIMITS.md §2 example)", () => {
    const report = {
      month: "2026-07",
      tenant: {
        budget_monthly_usd: 10.0,
        budget_source: "default",
        spend_usd: 1.234567,
        remaining_usd: 8.765433,
        input_tokens: 12345,
        output_tokens: 6789,
        requests: 42,
        exhausted: false,
      },
      agents: [
        {
          agent_id: "personal",
          budget_monthly_usd: 20.0,
          spend_usd: 1.2,
          remaining_usd: 18.8,
          input_tokens: 12000,
          output_tokens: 6000,
          requests: 40,
          exhausted: false,
        },
      ],
    };
    const parsed = UsageReportSchema.parse(report);
    expect(parsed.agents).toHaveLength(1);
    expect(parsed.tenant.budget_source).toBe("default");
  });

  it("accepts an empty agents list (fresh tenant)", () => {
    const parsed = UsageReportSchema.parse({
      month: "2026-07",
      tenant: {
        budget_monthly_usd: 10,
        budget_source: "default",
        spend_usd: 0,
        remaining_usd: 10,
        input_tokens: 0,
        output_tokens: 0,
        requests: 0,
        exhausted: false,
      },
      agents: [],
    });
    expect(parsed.agents).toHaveLength(0);
  });
});
