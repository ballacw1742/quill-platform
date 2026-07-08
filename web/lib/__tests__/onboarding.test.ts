/**
 * Onboarding content tests — Phase E. The first-run card set is copy-driven;
 * these guard that the exported steps/templates stay well-formed (every step
 * has a title+body, every CTA has an href, exactly the 3 templates) so a
 * future edit can't ship an empty/broken onboarding card.
 */
import { describe, expect, it } from "vitest";

import {
  ONBOARDING_STEPS,
  ONBOARDING_TEMPLATES,
} from "@/components/assistant/Onboarding";

describe("ONBOARDING_STEPS", () => {
  it("has the four canonical steps", () => {
    expect(ONBOARDING_STEPS.map((s) => s.key)).toEqual([
      "agent",
      "templates",
      "channels",
      "approvals",
    ]);
  });

  it("every step has a non-empty title and body", () => {
    for (const s of ONBOARDING_STEPS) {
      expect(s.title.trim().length).toBeGreaterThan(0);
      expect(s.body.trim().length).toBeGreaterThan(0);
    }
  });

  it("any step with a CTA also has an href, and vice versa", () => {
    for (const s of ONBOARDING_STEPS) {
      expect(Boolean(s.href)).toBe(Boolean(s.cta));
    }
  });

  it("links point at existing assistant surfaces", () => {
    const hrefs = ONBOARDING_STEPS.filter((s) => s.href).map((s) => s.href);
    expect(hrefs).toContain("/assistant/builder");
    expect(hrefs).toContain("/assistant/channels");
  });
});

describe("ONBOARDING_TEMPLATES", () => {
  it("lists exactly the 3 starter templates", () => {
    expect(ONBOARDING_TEMPLATES).toHaveLength(3);
    expect(ONBOARDING_TEMPLATES.map((t) => t.name)).toEqual([
      "Research Assistant",
      "Ops Analyst",
      "Project Copilot",
    ]);
  });
});
