import { describe, it, expect } from "vitest";
import {
  displayName,
  description,
  displayLane,
  laneTabLabel,
  laneAsNumber,
  displayPriority,
  displayEscalation,
  displayWorkflow,
  displayTrustTier,
  displayConfidence,
  prettyCase,
} from "../agent-meta";

describe("displayName", () => {
  it("returns the canonical name for a known agent_id", () => {
    expect(displayName("rfi-triage")).toBe("RFI Sorter");
    expect(displayName("submittal-spec-validator")).toBe("Spec Checker");
    expect(displayName("daily-brief")).toBe("Daily Brief");
  });

  it("falls back to pretty-cased input for unknown ids", () => {
    expect(displayName("unknown-helper")).toBe("Unknown helper");
    expect(displayName("foo_bar-baz")).toBe("Foo bar baz");
  });

  it("handles empty input gracefully", () => {
    expect(displayName(undefined)).toBe("Helper");
    expect(displayName(null)).toBe("Helper");
    expect(displayName("")).toBe("Helper");
  });
});

describe("description", () => {
  it("returns one-liner for known agents", () => {
    expect(description("rfi-triage")).toContain("RFIs");
    expect(description("procurement-watch")).toContain("long-lead");
  });

  it("returns empty string for unknown / missing", () => {
    expect(description("nope")).toBe("");
    expect(description(undefined)).toBe("");
  });
});

describe("displayLane / laneTabLabel", () => {
  it("maps API integer lanes to plain English", () => {
    expect(displayLane(1)).toBe("Auto-handled");
    expect(displayLane(2)).toBe("Needs your sign-off");
    expect(displayLane(3)).toBe("Needs two signatures");
  });

  it("accepts prompt-tier strings", () => {
    expect(displayLane("tier-2-auto")).toBe("Auto-handled");
    expect(displayLane("tier-1-spotcheck")).toBe("Needs your sign-off");
    expect(displayLane("tier-0-mandatory")).toBe("Needs two signatures");
  });

  it("returns short tab labels", () => {
    expect(laneTabLabel(1)).toBe("Auto");
    expect(laneTabLabel(2)).toBe("Yours");
    expect(laneTabLabel(3)).toBe("Two-signer");
    expect(laneTabLabel("tier-1-spotcheck")).toBe("Yours");
  });

  it("returns empty for unknown lanes", () => {
    expect(displayLane(0)).toBe("");
    expect(displayLane(99)).toBe("");
    expect(displayLane(undefined)).toBe("");
  });
});

describe("laneAsNumber", () => {
  it("normalizes representations to integer 1|2|3", () => {
    expect(laneAsNumber(1)).toBe(1);
    expect(laneAsNumber("tier-2-auto")).toBe(1);
    expect(laneAsNumber("tier-1-spotcheck")).toBe(2);
    expect(laneAsNumber("tier-0-mandatory")).toBe(3);
    expect(laneAsNumber("3")).toBe(3);
    expect(laneAsNumber(null)).toBe(null);
    expect(laneAsNumber("nope")).toBe(null);
  });
});

describe("displayPriority", () => {
  it("capitalizes known priorities", () => {
    expect(displayPriority("critical")).toBe("Critical");
    expect(displayPriority("high")).toBe("High");
    expect(displayPriority("normal")).toBe("Normal");
    expect(displayPriority("low")).toBe("Low");
  });

  it("falls back to pretty-case for unknown", () => {
    expect(displayPriority("urgent_now")).toBe("Urgent now");
  });

  it("defaults to Normal when missing", () => {
    expect(displayPriority(undefined)).toBe("Normal");
    expect(displayPriority("")).toBe("Normal");
  });
});

describe("displayEscalation", () => {
  it("maps known tags", () => {
    expect(displayEscalation("prompt_injection_detected")).toBe(
      "Suspicious content",
    );
    expect(displayEscalation("cost-impact")).toBe("Cost impact");
    expect(displayEscalation("schedule")).toBe("Schedule impact");
    expect(displayEscalation("safety")).toBe("Safety flag");
    expect(displayEscalation("long-lead")).toBe("Long-lead equipment");
    expect(displayEscalation("critical-path")).toBe("Critical path risk");
  });

  it("falls back to pretty-case for unknown tags", () => {
    expect(displayEscalation("custom_flag")).toBe("Custom flag");
  });

  it("returns empty for missing", () => {
    expect(displayEscalation(undefined)).toBe("");
  });
});

describe("displayWorkflow", () => {
  it("maps canonical workflows to plain English", () => {
    expect(displayWorkflow("rfi.classify")).toBe("Sort RFI");
    expect(displayWorkflow("submittal.validate")).toBe("Check submittal");
    expect(displayWorkflow("procurement.watch")).toBe("Watch procurement");
    expect(displayWorkflow("co.estimate")).toBe("Estimate change order");
  });

  it("derives a verb-noun phrasing for unknown two-part workflows", () => {
    // dotted unknown — generic split. The exact phrasing isn't important,
    // just that it doesn't leak the raw token.
    const out = displayWorkflow("widget.poke");
    expect(out.toLowerCase()).toContain("widget");
    expect(out.toLowerCase()).toContain("poke");
  });

  it("falls back to pretty-case for slug-like ids", () => {
    expect(displayWorkflow("approve_thing")).toBe("Approve thing");
  });

  it("defaults to 'Item' when missing", () => {
    expect(displayWorkflow(undefined)).toBe("Item");
    expect(displayWorkflow("")).toBe("Item");
  });
});

describe("displayTrustTier", () => {
  it("translates tier identifiers to plain English", () => {
    expect(displayTrustTier("tier-0")).toBe("Probation");
    expect(displayTrustTier("tier-1")).toBe("Standard");
    expect(displayTrustTier("tier-2")).toBe("Trusted");
    expect(displayTrustTier("trusted")).toBe("Trusted");
  });

  it("falls back to pretty-case for unknown", () => {
    expect(displayTrustTier("foo")).toBe("Foo");
  });
});

describe("displayConfidence", () => {
  it("formats 0–1 floats as a percent string", () => {
    expect(displayConfidence(0.78)).toBe("78% confident");
    expect(displayConfidence(0.5)).toBe("50% confident");
    expect(displayConfidence(1)).toBe("100% confident");
    expect(displayConfidence(0)).toBe("0% confident");
  });

  it("supports a no-suffix variant", () => {
    expect(displayConfidence(0.78, false)).toBe("78%");
  });

  it("clamps out-of-range values", () => {
    expect(displayConfidence(1.5)).toBe("100% confident");
    expect(displayConfidence(-0.1)).toBe("0% confident");
  });

  it("returns empty for missing", () => {
    expect(displayConfidence(undefined)).toBe("");
    expect(displayConfidence(null)).toBe("");
    expect(displayConfidence(NaN)).toBe("");
  });
});

describe("prettyCase", () => {
  it("converts snake/kebab/dotted slugs", () => {
    expect(prettyCase("rfi_triage")).toBe("Rfi triage");
    expect(prettyCase("rfi-triage")).toBe("Rfi triage");
    expect(prettyCase("rfi.triage")).toBe("Rfi triage");
  });

  it("handles empty / nullish", () => {
    expect(prettyCase(undefined)).toBe("");
    expect(prettyCase("")).toBe("");
  });
});
