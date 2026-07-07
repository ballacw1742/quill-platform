/**
 * Agent Cloud web-chat client tests — Sprint A5 (agent-cloud/WEBCHAT.md).
 * Pure-function coverage: SSE incremental parser, transcript → renderable
 * items, and schema validation of the contract shapes.
 */
import { describe, expect, it } from "vitest";

import {
  AgentChatResultSchema,
  AgentCloudAgentListSchema,
  AgentCloudSessionListSchema,
  AgentCloudTranscriptSchema,
  createSseParser,
  renderableMessages,
  type TranscriptMessage,
} from "@/lib/agent-cloud";

describe("createSseParser", () => {
  it("parses a complete multi-event stream", () => {
    const p = createSseParser();
    const events = p.push(
      'event: session\ndata: {"session_id": "abc"}\n\n' +
        'event: text\ndata: {"delta": "Hel"}\n\n' +
        'event: text\ndata: {"delta": "lo"}\n\n' +
        'event: tool\ndata: {"name": "get_time", "status": "start"}\n\n' +
        'event: tool\ndata: {"name": "get_time", "status": "ok"}\n\n' +
        'event: done\ndata: {"session_id": "abc", "reply": "Hello", "tool_calls": ["get_time"], "model": "m", "usage": {"input_tokens": 1, "output_tokens": 2, "cost_usd": 0.001}, "budget_exceeded": false}\n\n',
    );
    expect(events.map((e) => e.type)).toEqual([
      "session",
      "text",
      "text",
      "tool",
      "tool",
      "done",
    ]);
    const done = events[5];
    if (done.type !== "done") throw new Error("expected done");
    expect(done.result.reply).toBe("Hello");
    expect(done.result.budget_exceeded).toBe(false);
  });

  it("handles frames split across chunks (incremental buffering)", () => {
    const p = createSseParser();
    expect(p.push("event: text\ndata: {\"del")).toEqual([]);
    const events = p.push('ta": "hi"}\n\n');
    expect(events).toEqual([{ type: "text", delta: "hi" }]);
    expect(p.state.buffer).toBe("");
  });

  it("skips malformed and unknown frames without crashing", () => {
    const p = createSseParser();
    const events = p.push(
      "event: text\ndata: {not json}\n\n" +
        'event: mystery\ndata: {"x": 1}\n\n' +
        'event: text\ndata: {"delta": "ok"}\n\n',
    );
    expect(events).toEqual([{ type: "text", delta: "ok" }]);
  });

  it("parses the error event envelope", () => {
    const p = createSseParser();
    const events = p.push(
      'event: error\ndata: {"detail": "agent service unreachable", "status": 502}\n\n',
    );
    expect(events).toEqual([
      { type: "error", detail: "agent service unreachable", status: 502 },
    ]);
  });

  it("parses a budget-exceeded done event as a normal done", () => {
    const p = createSseParser();
    const events = p.push(
      'event: done\ndata: {"session_id": "s", "reply": "cap hit", "tool_calls": [], "model": "m", "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0}, "budget_exceeded": true}\n\n',
    );
    expect(events[0].type).toBe("done");
    if (events[0].type === "done") {
      expect(events[0].result.budget_exceeded).toBe(true);
    }
  });
});

describe("renderableMessages", () => {
  const t = (s: string) => s; // readability

  it("renders plain user/assistant text turns", () => {
    const messages: TranscriptMessage[] = [
      { role: "user", content: "hi", created_at: t("2026-07-07T12:00:00Z") },
      {
        role: "assistant",
        content: [{ type: "text", text: "hello" }],
        created_at: t("2026-07-07T12:00:01Z"),
      },
    ];
    expect(renderableMessages(messages)).toEqual([
      { kind: "user", text: "hi", created_at: "2026-07-07T12:00:00Z" },
      {
        kind: "assistant",
        text: "hello",
        tools: [],
        created_at: "2026-07-07T12:00:01Z",
      },
    ]);
  });

  it("folds tool_use/tool_result rounds into chips on the final bubble", () => {
    const messages: TranscriptMessage[] = [
      { role: "user", content: "time?", created_at: "1" },
      {
        role: "assistant",
        content: [
          { type: "text", text: "Let me check get_time." },
          { type: "tool_use", id: "tu1", name: "get_time", input: {} },
        ],
        created_at: "2",
      },
      {
        role: "user",
        content: [{ type: "tool_result", tool_use_id: "tu1", content: "12:00" }],
        created_at: "3",
      },
      {
        role: "assistant",
        content: [{ type: "text", text: "It is noon." }],
        created_at: "4",
      },
    ];
    const items = renderableMessages(messages);
    expect(items).toEqual([
      { kind: "user", text: "time?", created_at: "1" },
      { kind: "assistant", text: "It is noon.", tools: ["get_time"], created_at: "4" },
    ]);
  });

  it("renders [system wake] user messages as system rows", () => {
    const messages: TranscriptMessage[] = [
      {
        role: "user",
        content: [{ type: "text", text: "[system wake] Sub-agent job x completed." }],
        created_at: "1",
      },
    ];
    expect(renderableMessages(messages)).toEqual([
      {
        kind: "system",
        text: "[system wake] Sub-agent job x completed.",
        created_at: "1",
      },
    ]);
  });

  it("skips unknown block types without crashing", () => {
    const messages: TranscriptMessage[] = [
      {
        role: "assistant",
        content: [
          { type: "hologram", data: "??" },
          { type: "text", text: "still fine" },
        ],
        created_at: "1",
      },
    ];
    expect(renderableMessages(messages)).toEqual([
      { kind: "assistant", text: "still fine", tools: [], created_at: "1" },
    ]);
  });
});

describe("contract schemas (WEBCHAT.md §3)", () => {
  it("accepts the agents list envelope", () => {
    const parsed = AgentCloudAgentListSchema.parse({
      items: [
        {
          agent_id: "personal",
          model: "claude-fable-5",
          enabled: true,
          memory_policy: "auto_recall",
          budget_monthly_usd: 20.0,
          created_at: "2026-07-07T12:00:00+00:00",
        },
      ],
      total: 1,
      limit: 100,
      offset: 0,
    });
    expect(parsed.items[0].agent_id).toBe("personal");
  });

  it("accepts the sessions list envelope", () => {
    const parsed = AgentCloudSessionListSchema.parse({
      items: [
        {
          session_id: "s1",
          agent_id: "quill",
          preview: "arr?",
          created_at: "2026-07-07T12:00:00+00:00",
          updated_at: "2026-07-07T12:05:00+00:00",
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
    expect(parsed.items[0].preview).toBe("arr?");
  });

  it("accepts transcripts with string and block content", () => {
    const parsed = AgentCloudTranscriptSchema.parse({
      session_id: "s1",
      agent_id: "personal",
      created_at: "2026-07-07T12:00:00+00:00",
      updated_at: "2026-07-07T12:00:00+00:00",
      messages: [
        { role: "user", content: "hi", created_at: "2026-07-07T12:00:00+00:00" },
        {
          role: "assistant",
          content: [{ type: "text", text: "yo" }],
          created_at: "2026-07-07T12:00:01+00:00",
        },
      ],
    });
    expect(parsed.messages).toHaveLength(2);
  });

  it("defaults budget_exceeded to false on chat results", () => {
    const parsed = AgentChatResultSchema.parse({
      session_id: "s",
      reply: "r",
      tool_calls: [],
      model: "m",
      usage: { input_tokens: 1, output_tokens: 1, cost_usd: 0.1 },
    });
    expect(parsed.budget_exceeded).toBe(false);
  });
});
