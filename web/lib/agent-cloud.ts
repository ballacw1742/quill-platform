"use client";

/**
 * Agent Cloud web-chat client — Sprint A5.
 *
 * Contract: agent-cloud/WEBCHAT.md. Everything here talks to the Quill API
 * bridge at /api/v1/agent-cloud/* (Next.js rewrite → /v1/agent-cloud/*) with
 * the normal Quill Bearer JWT. tenant_id never appears on this side — the
 * bridge injects it server-side.
 *
 * The SSE reader + transcript renderer are exported as pure functions so
 * lib/__tests__/agent-cloud.test.ts can exercise them without a browser.
 */

import { useQuery, useQueryClient, type UseQueryOptions } from "@tanstack/react-query";
import { z } from "zod";

// ─── Schemas (WEBCHAT.md §3) ─────────────────────────────────────────────────

export const AgentCloudAgentSchema = z.object({
  agent_id: z.string(),
  model: z.string(),
  enabled: z.boolean(),
  memory_policy: z.string(),
  budget_monthly_usd: z.number(),
  created_at: z.string(),
});
export type AgentCloudAgent = z.infer<typeof AgentCloudAgentSchema>;

export const AgentCloudAgentListSchema = z.object({
  items: z.array(AgentCloudAgentSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
});
export type AgentCloudAgentList = z.infer<typeof AgentCloudAgentListSchema>;

export const AgentCloudSessionSchema = z.object({
  session_id: z.string(),
  agent_id: z.string(),
  preview: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type AgentCloudSession = z.infer<typeof AgentCloudSessionSchema>;

export const AgentCloudSessionListSchema = z.object({
  items: z.array(AgentCloudSessionSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
});
export type AgentCloudSessionList = z.infer<typeof AgentCloudSessionListSchema>;

/** content is verbatim what the orchestrator persisted: a plain string or a
 * content-block list (WEBCHAT.md §3.3). Keep the block schema permissive —
 * unknown block types must never crash rendering. */
export const TranscriptMessageSchema = z.object({
  role: z.string(),
  content: z.union([z.string(), z.array(z.record(z.unknown()))]),
  created_at: z.string(),
});
export type TranscriptMessage = z.infer<typeof TranscriptMessageSchema>;

export const AgentCloudTranscriptSchema = z.object({
  session_id: z.string(),
  agent_id: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  messages: z.array(TranscriptMessageSchema),
});
export type AgentCloudTranscript = z.infer<typeof AgentCloudTranscriptSchema>;

export const AgentChatUsageSchema = z.object({
  input_tokens: z.number(),
  output_tokens: z.number(),
  cost_usd: z.number(),
});

export const AgentChatResultSchema = z.object({
  session_id: z.string(),
  reply: z.string(),
  tool_calls: z.array(z.string()),
  model: z.string(),
  usage: AgentChatUsageSchema,
  budget_exceeded: z.boolean().default(false),
});
export type AgentChatResult = z.infer<typeof AgentChatResultSchema>;

// ─── SSE events (WEBCHAT.md §3.4) ────────────────────────────────────────────

export type AgentChatStreamEvent =
  | { type: "session"; session_id: string }
  | { type: "text"; delta: string }
  | { type: "tool"; name: string; status: "start" | "ok" | "denied" }
  | { type: "done"; result: AgentChatResult }
  | { type: "error"; detail: string; status: number };

/**
 * Incremental SSE parser. Feed it raw text chunks; it returns fully-parsed
 * events and keeps the unterminated tail in `state.buffer`. Pure — unit
 * tested directly.
 */
export function createSseParser() {
  const state = { buffer: "" };
  function push(chunk: string): AgentChatStreamEvent[] {
    state.buffer += chunk;
    const events: AgentChatStreamEvent[] = [];
    let sep: number;
    // SSE frames are separated by a blank line.
    while ((sep = state.buffer.indexOf("\n\n")) !== -1) {
      const frame = state.buffer.slice(0, sep);
      state.buffer = state.buffer.slice(sep + 2);
      let eventName = "";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) eventName = line.slice(7).trim();
        else if (line.startsWith("data: ")) data += line.slice(6);
        else if (line.startsWith("data:")) data += line.slice(5);
      }
      if (!eventName || !data) continue;
      const ev = toStreamEvent(eventName, data);
      if (ev) events.push(ev);
    }
    return events;
  }
  return { push, state };
}

function toStreamEvent(name: string, data: string): AgentChatStreamEvent | null {
  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(data) as Record<string, unknown>;
  } catch {
    return null; // malformed frame — skip, never crash the stream
  }
  switch (name) {
    case "session":
      return { type: "session", session_id: String(parsed.session_id ?? "") };
    case "text":
      return { type: "text", delta: String(parsed.delta ?? "") };
    case "tool":
      return {
        type: "tool",
        name: String(parsed.name ?? ""),
        status: (parsed.status as "start" | "ok" | "denied") ?? "start",
      };
    case "done": {
      const result = AgentChatResultSchema.safeParse(parsed);
      if (!result.success) return null;
      return { type: "done", result: result.data };
    }
    case "error":
      return {
        type: "error",
        detail: String(parsed.detail ?? "unknown error"),
        status: Number(parsed.status ?? 500),
      };
    default:
      return null; // unknown event type — forward-compatible skip
  }
}

// ─── Transcript → renderable items (WEBCHAT.md §3.3 rendering rules) ─────────

export type RenderableItem =
  | { kind: "user"; text: string; created_at: string }
  | { kind: "assistant"; text: string; tools: string[]; created_at: string }
  | { kind: "system"; text: string; created_at: string };

const SYSTEM_WAKE_PREFIX = "[system wake]";

function textFromBlocks(blocks: Array<Record<string, unknown>>): string {
  return blocks
    .filter((b) => b.type === "text" && typeof b.text === "string")
    .map((b) => b.text as string)
    .join("");
}

function toolsFromBlocks(blocks: Array<Record<string, unknown>>): string[] {
  return blocks
    .filter((b) => b.type === "tool_use" && typeof b.name === "string")
    .map((b) => b.name as string);
}

/**
 * Collapse the raw persisted message stream into displayable chat items:
 *  - user strings → user bubbles
 *  - assistant block lists → one assistant bubble per final text, with any
 *    tool_use names folded into the *following* assistant bubble's chips
 *  - tool_result-only user messages → dropped (represented by the chips)
 *  - "[system wake] …" user messages → muted system rows
 *  - unknown block types → skipped
 */
export function renderableMessages(messages: TranscriptMessage[]): RenderableItem[] {
  const items: RenderableItem[] = [];
  let pendingTools: string[] = [];

  for (const m of messages) {
    if (typeof m.content === "string") {
      if (m.role === "user") {
        items.push({ kind: "user", text: m.content, created_at: m.created_at });
      } else {
        items.push({
          kind: "assistant",
          text: m.content,
          tools: pendingTools,
          created_at: m.created_at,
        });
        pendingTools = [];
      }
      continue;
    }

    const blocks = m.content;
    const text = textFromBlocks(blocks);
    const tools = toolsFromBlocks(blocks);

    if (m.role === "user") {
      // tool_result-only rows carry no text; wake rows start with the marker.
      if (text.startsWith(SYSTEM_WAKE_PREFIX)) {
        items.push({ kind: "system", text, created_at: m.created_at });
      } else if (text.trim()) {
        items.push({ kind: "user", text, created_at: m.created_at });
      }
      continue;
    }

    // assistant
    pendingTools.push(...tools);
    if (text.trim() && blocks.every((b) => b.type !== "tool_use")) {
      // final text turn — attach accumulated tool chips
      items.push({
        kind: "assistant",
        text,
        tools: pendingTools,
        created_at: m.created_at,
      });
      pendingTools = [];
    }
  }

  // trailing tool-only assistant turn (mid-flight transcript)
  if (pendingTools.length > 0) {
    items.push({
      kind: "assistant",
      text: "",
      tools: pendingTools,
      created_at: messages[messages.length - 1]?.created_at ?? "",
    });
  }
  return items;
}

// ─── Fetch helpers ───────────────────────────────────────────────────────────

const API_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) || "";

export class AgentCloudError extends Error {
  constructor(public status: number, msg: string) {
    super(msg);
    this.name = "AgentCloudError";
  }
}

function token(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("quill_session_token");
}

function authHeaders(): Record<string, string> {
  const t = token();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function getJson<T>(path: string, schema: z.ZodType<T>): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...authHeaders() },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* keep statusText */
    }
    throw new AgentCloudError(res.status, detail);
  }
  return schema.parse(await res.json());
}

// ─── Query hooks ─────────────────────────────────────────────────────────────

export function useAgentCloudAgents(
  opts?: Partial<UseQueryOptions<AgentCloudAgentList>>,
) {
  return useQuery<AgentCloudAgentList>({
    queryKey: ["agent-cloud", "agents"],
    queryFn: () => getJson("/api/v1/agent-cloud/agents", AgentCloudAgentListSchema),
    staleTime: 60_000,
    ...opts,
  });
}

export function useAgentCloudSessions(
  agentId: string | null,
  opts?: Partial<UseQueryOptions<AgentCloudSessionList>>,
) {
  const qs = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : "";
  return useQuery<AgentCloudSessionList>({
    queryKey: ["agent-cloud", "sessions", agentId ?? "all"],
    queryFn: () =>
      getJson(`/api/v1/agent-cloud/sessions${qs}`, AgentCloudSessionListSchema),
    ...opts,
  });
}

export function useAgentCloudTranscript(
  sessionId: string | null,
  opts?: Partial<UseQueryOptions<AgentCloudTranscript | undefined>>,
) {
  return useQuery<AgentCloudTranscript | undefined>({
    queryKey: ["agent-cloud", "transcript", sessionId],
    queryFn: async () => {
      if (!sessionId) return undefined;
      return getJson(
        `/api/v1/agent-cloud/sessions/${encodeURIComponent(sessionId)}`,
        AgentCloudTranscriptSchema,
      );
    },
    enabled: !!sessionId,
    ...opts,
  });
}

/** Invalidate agent-cloud queries after a completed turn. */
export function useInvalidateAgentCloud() {
  const qc = useQueryClient();
  return (sessionId?: string | null) => {
    void qc.invalidateQueries({ queryKey: ["agent-cloud", "sessions"] });
    if (sessionId) {
      void qc.invalidateQueries({ queryKey: ["agent-cloud", "transcript", sessionId] });
    }
  };
}

// ─── Chat send (SSE with non-stream fallback) ────────────────────────────────

export type SendHandlers = {
  onEvent: (ev: AgentChatStreamEvent) => void;
  signal?: AbortSignal;
};

/**
 * Send one chat turn. Tries SSE streaming first; if the response isn't an
 * event stream (or the environment can't read body streams) it falls back to
 * a plain JSON turn and synthesizes the equivalent events, so the caller
 * handles exactly one shape.
 *
 * Errors before any byte arrives throw AgentCloudError; errors mid-stream
 * arrive as an `error` event (matching the bridge contract).
 */
export async function sendAgentChat(
  args: { agentId: string; message: string; sessionId?: string | null },
  handlers: SendHandlers,
): Promise<void> {
  const body = JSON.stringify({
    agent_id: args.agentId,
    message: args.message,
    ...(args.sessionId ? { session_id: args.sessionId } : {}),
    stream: true,
  });

  const res = await fetch(`${API_BASE}/api/v1/agent-cloud/chat`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body,
    signal: handlers.signal,
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* keep statusText */
    }
    throw new AgentCloudError(res.status, detail);
  }

  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("text/event-stream") && res.body) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    const parser = createSseParser();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const ev of parser.push(decoder.decode(value, { stream: true }))) {
        handlers.onEvent(ev);
      }
    }
    return;
  }

  // Fallback: server answered non-stream JSON (or streaming unsupported).
  await nonStreamFallback(args, handlers);
}

export async function nonStreamFallback(
  args: { agentId: string; message: string; sessionId?: string | null },
  handlers: SendHandlers,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/agent-cloud/chat`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({
      agent_id: args.agentId,
      message: args.message,
      ...(args.sessionId ? { session_id: args.sessionId } : {}),
      stream: false,
    }),
    signal: handlers.signal,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* keep statusText */
    }
    throw new AgentCloudError(res.status, detail);
  }
  const result = AgentChatResultSchema.parse(await res.json());
  handlers.onEvent({ type: "session", session_id: result.session_id });
  for (const name of result.tool_calls) {
    handlers.onEvent({ type: "tool", name, status: "ok" });
  }
  if (result.reply) handlers.onEvent({ type: "text", delta: result.reply });
  handlers.onEvent({ type: "done", result });
}
