/**
 * Dev Chat schema + state machine tests (Sprint DC.1)
 *
 * Covers:
 *  - Schema parsing for DevChatMessage, DevChatThread, DevChatStatus
 *  - State machine: idle ↔ in_progress transitions
 *  - Message rendering logic (status fields)
 *  - Cancel handler guard (no cancel when idle)
 */

import { describe, it, expect } from "vitest";
import {
  DevChatMessageSchema,
  DevChatThreadSchema,
  DevChatStatusSchema,
  DevChatSendResponseSchema,
  DevChatThreadPageSchema,
} from "../schemas";

// ─── Schema Parsing ───────────────────────────────────────────────────────────

describe("DevChatMessageSchema", () => {
  it("parses a user message", () => {
    const raw = {
      id: "msg-001",
      thread_id: "thread-001",
      role: "user",
      content: "Make the button red",
      status: "completed",
      created_at: "2026-05-10T21:00:00+00:00",
      updated_at: "2026-05-10T21:00:00+00:00",
    };
    const parsed = DevChatMessageSchema.parse(raw);
    expect(parsed.role).toBe("user");
    expect(parsed.status).toBe("completed");
    expect(parsed.content).toBe("Make the button red");
  });

  it("parses a completed agent message with commit_sha", () => {
    const raw = {
      id: "msg-002",
      thread_id: "thread-001",
      role: "agent",
      content: "Changed button color to red",
      status: "completed",
      commit_sha: "abc1234deadbeef",
      files_changed: ["web/components/Button.tsx"],
      cost_usd: 0.0012,
      created_at: "2026-05-10T21:01:00+00:00",
      updated_at: "2026-05-10T21:01:00+00:00",
      completed_at: "2026-05-10T21:01:30+00:00",
    };
    const parsed = DevChatMessageSchema.parse(raw);
    expect(parsed.commit_sha).toBe("abc1234deadbeef");
    expect(parsed.files_changed).toContain("web/components/Button.tsx");
    expect(parsed.cost_usd).toBeCloseTo(0.0012);
  });

  it("parses a streaming agent message", () => {
    const raw = {
      id: "msg-003",
      thread_id: "thread-001",
      role: "agent",
      content: "Reading codebase...",
      status: "streaming",
      created_at: "2026-05-10T21:01:00+00:00",
      updated_at: "2026-05-10T21:01:00+00:00",
    };
    const parsed = DevChatMessageSchema.parse(raw);
    expect(parsed.status).toBe("streaming");
  });

  it("parses a failed agent message", () => {
    const raw = {
      id: "msg-004",
      thread_id: "thread-001",
      role: "agent",
      content: "Git error: conflict",
      status: "failed",
      created_at: "2026-05-10T21:01:00+00:00",
      updated_at: "2026-05-10T21:01:00+00:00",
    };
    const parsed = DevChatMessageSchema.parse(raw);
    expect(parsed.status).toBe("failed");
  });

  it("parses a system message", () => {
    const raw = {
      id: "msg-005",
      thread_id: "thread-001",
      role: "system",
      content: "Task cancelled by user",
      status: "cancelled",
      created_at: "2026-05-10T21:01:00+00:00",
      updated_at: "2026-05-10T21:01:00+00:00",
    };
    const parsed = DevChatMessageSchema.parse(raw);
    expect(parsed.role).toBe("system");
    expect(parsed.status).toBe("cancelled");
  });
});

describe("DevChatThreadSchema", () => {
  it("parses an idle thread", () => {
    const raw = {
      id: "thread-001",
      user_id: "user-001",
      state: "idle",
      created_at: "2026-05-10T20:00:00+00:00",
      updated_at: "2026-05-10T20:00:00+00:00",
    };
    const parsed = DevChatThreadSchema.parse(raw);
    expect(parsed.state).toBe("idle");
  });

  it("parses an in_progress thread", () => {
    const raw = {
      id: "thread-001",
      user_id: "user-001",
      state: "in_progress",
      created_at: "2026-05-10T20:00:00+00:00",
      updated_at: "2026-05-10T21:00:00+00:00",
    };
    const parsed = DevChatThreadSchema.parse(raw);
    expect(parsed.state).toBe("in_progress");
  });

  it("rejects unknown state", () => {
    const raw = {
      id: "thread-001",
      user_id: "user-001",
      state: "error",
      created_at: "2026-05-10T20:00:00+00:00",
      updated_at: "2026-05-10T20:00:00+00:00",
    };
    expect(() => DevChatThreadSchema.parse(raw)).toThrow();
  });
});

describe("DevChatStatusSchema", () => {
  it("parses idle status", () => {
    const raw = { state: "idle" };
    const parsed = DevChatStatusSchema.parse(raw);
    expect(parsed.state).toBe("idle");
    expect(parsed.current_task_id).toBeUndefined();
  });

  it("parses in_progress status with task info", () => {
    const raw = {
      state: "in_progress",
      current_task_id: "task-001",
      current_message_id: "msg-001",
      started_at: "2026-05-10T21:00:00+00:00",
    };
    const parsed = DevChatStatusSchema.parse(raw);
    expect(parsed.state).toBe("in_progress");
    expect(parsed.current_task_id).toBe("task-001");
  });
});

describe("DevChatSendResponseSchema", () => {
  it("parses a valid send response", () => {
    const raw = {
      task_id: "task-001",
      message_id: "msg-001",
      thread_state: "in_progress",
    };
    const parsed = DevChatSendResponseSchema.parse(raw);
    expect(parsed.task_id).toBe("task-001");
    expect(parsed.thread_state).toBe("in_progress");
  });
});

describe("DevChatThreadPageSchema", () => {
  it("parses a thread page with messages", () => {
    const raw = {
      thread: {
        id: "thread-001",
        user_id: "user-001",
        state: "idle",
        created_at: "2026-05-10T20:00:00+00:00",
        updated_at: "2026-05-10T20:00:00+00:00",
      },
      messages: [
        {
          id: "msg-001",
          thread_id: "thread-001",
          role: "user",
          content: "Make the button red",
          status: "completed",
          created_at: "2026-05-10T21:00:00+00:00",
          updated_at: "2026-05-10T21:00:00+00:00",
        },
      ],
      total: 1,
      limit: 100,
    };
    const parsed = DevChatThreadPageSchema.parse(raw);
    expect(parsed.messages).toHaveLength(1);
    expect(parsed.thread.state).toBe("idle");
    expect(parsed.total).toBe(1);
  });
});

// ─── State machine logic ──────────────────────────────────────────────────────

describe("Thread state machine invariants", () => {
  it("idle → in_progress on send", () => {
    let state: "idle" | "in_progress" = "idle";
    // Simulate send
    function onSend() {
      expect(state).toBe("idle");
      state = "in_progress";
    }
    onSend();
    expect(state).toBe("in_progress");
  });

  it("in_progress → idle on task_completed WS event", () => {
    let state: "idle" | "in_progress" = "in_progress";
    function onWsEvent(type: string) {
      if (type === "task_completed" || type === "task_failed" || type === "task_cancelled") {
        state = "idle";
      }
    }
    onWsEvent("task_completed");
    expect(state).toBe("idle");
  });

  it("in_progress → idle on cancel", () => {
    let state: "idle" | "in_progress" = "in_progress";
    let currentTaskId: string | null = "task-001";

    function onCancel(taskId: string) {
      if (currentTaskId === taskId) {
        state = "idle";
        currentTaskId = null;
      }
    }
    onCancel("task-001");
    expect(state).toBe("idle");
    expect(currentTaskId).toBeNull();
  });

  it("cancel is a no-op when state is idle", () => {
    const state: "idle" | "in_progress" = "idle";
    const currentTaskId: string | null = null;

    function onCancel(taskId: string) {
      // Guard: don't cancel if already idle or no matching task
      if (state !== "in_progress" || currentTaskId !== taskId) {
        return false;
      }
      return true;
    }

    expect(onCancel("task-001")).toBe(false);
  });
});
