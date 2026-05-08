import { describe, it, expect } from "vitest";
import {
  artifactTypeIcon,
  artifactTypeLabel,
  artifactTypeTone,
  filterToArtifactType,
  DOCUMENT_FILTER_OPTIONS,
} from "../document-meta";

describe("artifactTypeIcon", () => {
  it("returns the canonical lucide icon for each known artifact_type", () => {
    // Icons are lucide components; we just check we got SOMETHING and that
    // unknown types fall back consistently.
    expect(artifactTypeIcon("status_update")).toBeTruthy();
    expect(artifactTypeIcon("coordinator_artifact")).toBeTruthy();
    expect(artifactTypeIcon("pm_analysis")).toBeTruthy();
    expect(artifactTypeIcon("comms_draft")).toBeTruthy();
    expect(artifactTypeIcon("knowledge_entry")).toBeTruthy();
  });

  it("falls back to a non-null icon for unknown / null inputs", () => {
    expect(artifactTypeIcon(null)).toBeTruthy();
    expect(artifactTypeIcon(undefined)).toBeTruthy();
    expect(artifactTypeIcon("brand_new_type")).toBeTruthy();
  });
});

describe("artifactTypeLabel", () => {
  it("returns the plain-English label for each canonical artifact_type", () => {
    expect(artifactTypeLabel("status_update")).toBe("Status update");
    expect(artifactTypeLabel("coordinator_artifact")).toBe("Process doc");
    expect(artifactTypeLabel("pm_analysis")).toBe("Analysis");
    expect(artifactTypeLabel("comms_draft")).toBe("Comms draft");
    expect(artifactTypeLabel("knowledge_entry")).toBe("Knowledge entry");
  });

  it("refines coordinator_artifact via metadata.kind", () => {
    expect(artifactTypeLabel("coordinator_artifact", { kind: "SOP" })).toBe(
      "SOP",
    );
    expect(artifactTypeLabel("coordinator_artifact", { kind: "raci" })).toBe(
      "RACI",
    );
    expect(
      artifactTypeLabel("coordinator_artifact", { kind: "Action_Items" }),
    ).toBe("Action items");
    expect(
      artifactTypeLabel("coordinator_artifact", { kind: "agenda" }),
    ).toBe("Agenda");
    expect(
      artifactTypeLabel("coordinator_artifact", { kind: "unknown_kind" }),
    ).toBe("Process doc");
  });

  it("falls back to a pretty-cased label for unknown artifact_types", () => {
    expect(artifactTypeLabel("brand_new_type")).toBe("Brand new type");
  });

  it("returns 'Document' for null / undefined inputs", () => {
    expect(artifactTypeLabel(null)).toBe("Document");
    expect(artifactTypeLabel(undefined)).toBe("Document");
  });
});

describe("artifactTypeTone", () => {
  it("returns a tone token from the design system palette", () => {
    const valid = ["neutral", "accent", "info", "success", "warning", "danger"];
    expect(valid).toContain(artifactTypeTone("status_update"));
    expect(valid).toContain(artifactTypeTone("coordinator_artifact"));
    expect(valid).toContain(artifactTypeTone("pm_analysis"));
    expect(valid).toContain(artifactTypeTone("comms_draft"));
    expect(valid).toContain(artifactTypeTone("knowledge_entry"));
    expect(valid).toContain(artifactTypeTone("anything_else"));
  });
});

describe("filterToArtifactType", () => {
  it("returns undefined for 'all' (no filter applied)", () => {
    expect(filterToArtifactType("all")).toBeUndefined();
  });

  it("returns the matching artifact_type for each non-all filter value", () => {
    expect(filterToArtifactType("status_update")).toBe("status_update");
    expect(filterToArtifactType("coordinator_artifact")).toBe(
      "coordinator_artifact",
    );
    expect(filterToArtifactType("pm_analysis")).toBe("pm_analysis");
    expect(filterToArtifactType("comms_draft")).toBe("comms_draft");
    expect(filterToArtifactType("knowledge_entry")).toBe("knowledge_entry");
  });
});

describe("DOCUMENT_FILTER_OPTIONS", () => {
  it("starts with 'All' and covers every artifact_type", () => {
    expect(DOCUMENT_FILTER_OPTIONS[0]?.value).toBe("all");
    const values = DOCUMENT_FILTER_OPTIONS.map((o) => o.value);
    expect(values).toEqual([
      "all",
      "status_update",
      "coordinator_artifact",
      "pm_analysis",
      "comms_draft",
      "knowledge_entry",
    ]);
  });

  it("uses sentence-case labels (no developer jargon)", () => {
    for (const opt of DOCUMENT_FILTER_OPTIONS) {
      const label = opt.label;
      expect(label.length).toBeGreaterThan(0);
      // Per COPY_GUIDE: sentence case; first letter upper, rest typically lower.
      expect(label[0]).toBe(label[0].toUpperCase());
    }
  });
});
