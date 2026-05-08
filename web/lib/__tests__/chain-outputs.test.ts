import { describe, it, expect } from "vitest";
import { getChainOutputs, ChainOutputsSchema } from "../schemas";

describe("getChainOutputs", () => {
  it("returns null when payload is undefined", () => {
    expect(getChainOutputs(undefined)).toBeNull();
  });

  it("returns null when chain_outputs is missing", () => {
    expect(getChainOutputs({ rfi_id: "RFI-1" })).toBeNull();
  });

  it("returns null when chain_outputs is malformed", () => {
    expect(getChainOutputs({ chain_outputs: "not an object" })).toBeNull();
    expect(getChainOutputs({ chain_outputs: { steps: "nope" } })).toBeNull();
  });

  it("parses a well-formed chain_outputs blob", () => {
    const payload = {
      rfi_id: "RFI-001",
      chain_outputs: {
        chain_id: "rfi.full_triage",
        steps: [
          {
            agent_id: "rfi-triage",
            ok: true,
            confidence: 0.84,
            output: { discipline: "structural", priority: "normal" },
            model: "claude-opus-4-7",
            latency_ms: 1840,
          },
          {
            agent_id: "rfi-drafter",
            ok: true,
            confidence: 0.91,
            output: { draft_markdown: "## Response\nSee S-201." },
          },
        ],
        skipped: [],
        errors: [],
      },
    };
    const chain = getChainOutputs(payload);
    expect(chain).not.toBeNull();
    expect(chain!.chain_id).toBe("rfi.full_triage");
    expect(chain!.steps).toHaveLength(2);
    expect(chain!.steps[0].agent_id).toBe("rfi-triage");
    expect(chain!.steps[1].output?.draft_markdown).toContain("## Response");
  });

  it("preserves unknown step fields via passthrough", () => {
    const payload = {
      chain_outputs: {
        chain_id: "x",
        steps: [
          {
            agent_id: "a",
            ok: true,
            output: {},
            future_field: "kept",
          },
        ],
      },
    };
    const chain = getChainOutputs(payload);
    expect(chain).not.toBeNull();
    // passthrough keeps unknown fields:
    expect((chain!.steps[0] as Record<string, unknown>).future_field).toBe(
      "kept",
    );
  });

  it("schema rejects when required fields are missing", () => {
    const result = ChainOutputsSchema.safeParse({ steps: [] });
    expect(result.success).toBe(false);
  });
});
