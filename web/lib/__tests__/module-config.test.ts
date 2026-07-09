/**
 * Modular Framework Phase 0 — module config schema + ordering tests.
 * Pure (no network/React): validates the client contract shapes and the
 * enabled-filter + order-merge logic used by the home grid.
 */
import { describe, expect, it } from "vitest";

import {
  ModuleConfigItemSchema,
  ModuleConfigListSchema,
  type ModuleConfigItem,
} from "@/lib/api";
import { MODULE_ROSTER } from "@/lib/modules";

describe("ModuleConfigItemSchema", () => {
  it("parses an enabled module row", () => {
    const m = ModuleConfigItemSchema.parse({
      key: "finance",
      label: "Finance",
      enabled: true,
      sort_order: 11,
    });
    expect(m.key).toBe("finance");
    expect(m.enabled).toBe(true);
  });

  it("parses a disabled module row", () => {
    const m = ModuleConfigItemSchema.parse({
      key: "sites",
      label: "Sites",
      enabled: false,
      sort_order: 3,
    });
    expect(m.enabled).toBe(false);
  });

  it("rejects a malformed row (missing enabled)", () => {
    expect(() =>
      ModuleConfigItemSchema.parse({ key: "x", label: "X", sort_order: 0 }),
    ).toThrow();
  });
});

describe("ModuleConfigListSchema", () => {
  it("parses the full 15-module roster response", () => {
    const items = MODULE_ROSTER.map((m, i) => ({
      key: m.key,
      label: m.label,
      enabled: true,
      sort_order: i,
    }));
    const parsed = ModuleConfigListSchema.parse({ items });
    expect(parsed.items).toHaveLength(15);
  });
});

// Mirror of the home-grid visible-modules derivation (app/page.tsx) so the
// filter + order behavior is locked by a test.
function visibleKeys(
  roster: { key: string }[],
  cfg: ModuleConfigItem[] | undefined,
): string[] {
  const rosterOrder = new Map(roster.map((m, i) => [m.key, i] as const));
  if (!cfg || cfg.length === 0) return roster.map((m) => m.key);
  const enabled = new Set(cfg.filter((c) => c.enabled).map((c) => c.key));
  const orderOf = new Map(cfg.map((c) => [c.key, c.sort_order] as const));
  return roster
    .filter((m) => enabled.has(m.key))
    .sort(
      (a, b) =>
        (orderOf.get(a.key) ?? rosterOrder.get(a.key)!) -
          (orderOf.get(b.key) ?? rosterOrder.get(b.key)!) ||
        rosterOrder.get(a.key)! - rosterOrder.get(b.key)!,
    )
    .map((m) => m.key);
}

describe("home grid visible-modules derivation", () => {
  const roster = MODULE_ROSTER.map((m) => ({ key: m.key }));

  it("falls back to full roster when config is absent", () => {
    expect(visibleKeys(roster, undefined)).toEqual(roster.map((m) => m.key));
  });

  it("hides disabled modules", () => {
    const cfg: ModuleConfigItem[] = MODULE_ROSTER.map((m, i) => ({
      key: m.key,
      label: m.label,
      enabled: m.key !== "finance",
      sort_order: i,
    }));
    const keys = visibleKeys(roster, cfg);
    expect(keys).not.toContain("finance");
    expect(keys).toHaveLength(14);
  });

  it("applies configured order (agents pinned to front)", () => {
    const cfg: ModuleConfigItem[] = MODULE_ROSTER.map((m, i) => ({
      key: m.key,
      label: m.label,
      enabled: true,
      sort_order: m.key === "agents" ? -1 : i,
    }));
    expect(visibleKeys(roster, cfg)[0]).toBe("agents");
  });
});

describe("ModuleFeatureItem + features on config", () => {
  it("parses a module with a feature list", () => {
    const parsed = ModuleConfigItemSchema.parse({
      key: "contracts",
      label: "Contracts",
      enabled: true,
      sort_order: 4,
      features: [
        { key: "e_sign", label: "E-signature", enabled: false },
        { key: "templates", label: "Templates", enabled: true },
      ],
    });
    expect(parsed.features).toHaveLength(2);
    expect(parsed.features[0].enabled).toBe(false);
  });

  it("defaults features to [] when omitted (back-compat)", () => {
    const parsed = ModuleConfigItemSchema.parse({
      key: "approvals",
      label: "Approvals",
      enabled: true,
      sort_order: 1,
    });
    expect(parsed.features).toEqual([]);
  });
});

import { ModulePresetSchema } from "@/lib/api";

describe("ModulePresetSchema", () => {
  it("parses a preset", () => {
    const p = ModulePresetSchema.parse({
      key: "small-project",
      label: "Small project",
      description: "Lean set.",
      modules: ["requests", "projects", "agents"],
    });
    expect(p.modules).toContain("projects");
  });
});
