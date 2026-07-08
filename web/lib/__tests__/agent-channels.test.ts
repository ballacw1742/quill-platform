/**
 * Channel pairing web client tests — Phase D (agent-cloud/CHANNELS.md §12/§13).
 * Pure coverage: contract-shape schema validation + platform-label mapping.
 * The bridge (auth + tenant injection + passthrough) is covered in the api
 * test suite; here we only guard the wire shapes the UI parses.
 */
import { describe, expect, it } from "vitest";

import {
  CHANNEL_PLATFORMS,
  CHANNEL_PLATFORM_LABELS,
  ChannelLinkListSchema,
  ChannelPairResultSchema,
  ChannelRevokeResultSchema,
} from "@/lib/agent-cloud";

describe("channel platform metadata", () => {
  it("exposes exactly telegram + googlechat", () => {
    expect([...CHANNEL_PLATFORMS]).toEqual(["telegram", "googlechat"]);
  });

  it("has a human label for every platform", () => {
    for (const p of CHANNEL_PLATFORMS) {
      expect(CHANNEL_PLATFORM_LABELS[p]).toBeTruthy();
    }
    expect(CHANNEL_PLATFORM_LABELS.telegram).toBe("Telegram");
    expect(CHANNEL_PLATFORM_LABELS.googlechat).toBe("Google Chat");
  });
});

describe("contract schemas (CHANNELS.md §12)", () => {
  it("parses the pairing-code result", () => {
    const parsed = ChannelPairResultSchema.parse({
      link_id: "22222222-2222-2222-2222-222222222222",
      platform: "telegram",
      agent_id: "personal",
      status: "pending",
      pairing_code: "ABCD2345EFGH",
      expires_at: "2026-07-07T12:15:00+00:00",
      instructions: "send the code to the bot",
    });
    expect(parsed.pairing_code).toBe("ABCD2345EFGH");
    expect(parsed.status).toBe("pending");
  });

  it("accepts a null expires_at on the pair result", () => {
    const parsed = ChannelPairResultSchema.parse({
      link_id: "x",
      platform: "googlechat",
      agent_id: "quill",
      status: "pending",
      pairing_code: "CODE",
      expires_at: null,
      instructions: "…",
    });
    expect(parsed.expires_at).toBeNull();
  });

  it("parses a link list with linked + pending rows", () => {
    const parsed = ChannelLinkListSchema.parse({
      items: [
        {
          link_id: "a",
          platform: "telegram",
          agent_id: "personal",
          status: "linked",
          platform_chat_id: "555",
          display_name: "Charles",
          created_at: "2026-07-07T12:00:00+00:00",
          linked_at: "2026-07-07T12:05:00+00:00",
        },
        {
          link_id: "b",
          platform: "googlechat",
          agent_id: "quill",
          status: "pending",
          platform_chat_id: null,
          display_name: null,
          created_at: "2026-07-07T12:00:00+00:00",
          linked_at: null,
        },
      ],
      total: 2,
      limit: 100,
      offset: 0,
    });
    expect(parsed.items).toHaveLength(2);
    expect(parsed.items[1].platform_chat_id).toBeNull();
    expect(parsed.items[1].linked_at).toBeNull();
  });

  it("parses the revoke result", () => {
    const parsed = ChannelRevokeResultSchema.parse({
      link_id: "a",
      status: "revoked",
    });
    expect(parsed.status).toBe("revoked");
  });

  it("rejects a link row missing a required field", () => {
    expect(() =>
      ChannelLinkListSchema.parse({
        items: [{ link_id: "a", platform: "telegram" }],
        total: 1,
        limit: 100,
        offset: 0,
      }),
    ).toThrow();
  });
});
