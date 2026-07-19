import { describe, expect, it } from "vitest";
import type { Site } from "@/lib/schemas";
import { isRejectedSite, isSiteInProgress, siteFinalVerdict } from "@/lib/sites";

function makeSite(partial: Partial<Site>): Site {
  return {
    site_id: "s1",
    status: "intake",
    property: {},
    scores: {},
    recommendation: {},
    documents: [],
    decision: {},
    ...partial,
  } as Site;
}

describe("site queue/archive predicates", () => {
  it("siteFinalVerdict reads decision.final_verdict, null when unset", () => {
    expect(siteFinalVerdict(makeSite({}))).toBeNull();
    expect(
      siteFinalVerdict(makeSite({ decision: { final_verdict: "rejected" } })),
    ).toBe("rejected");
  });

  it("isRejectedSite is true only for a rejected decision", () => {
    expect(isRejectedSite(makeSite({ decision: { final_verdict: "rejected" } }))).toBe(true);
    expect(isRejectedSite(makeSite({ decision: { final_verdict: "accepted" } }))).toBe(false);
    expect(isRejectedSite(makeSite({}))).toBe(false);
  });

  it("in-progress excludes decided and rejected sites", () => {
    // Still evaluating → in progress.
    expect(isSiteInProgress(makeSite({ status: "review" }))).toBe(true);
    expect(isSiteInProgress(makeSite({ status: "researching" }))).toBe(true);
    // Decided (accepted/advanced) → out of the queue.
    expect(isSiteInProgress(makeSite({ status: "decided" }))).toBe(false);
    // Rejected → archived, out of the queue (even if status somehow not decided).
    expect(
      isSiteInProgress(
        makeSite({ status: "review", decision: { final_verdict: "rejected" } }),
      ),
    ).toBe(false);
  });
});
