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

// ─── Agent Builder (Phase C, AGENT_BUILDER.md) ───────────────────────────────

/** Detail shape (§1): superset of the list dict — adds system_prompt, tools,
 * is_seed. Returned by GET/POST/PATCH agents/{id}. */
export const AgentDetailSchema = z.object({
  agent_id: z.string(),
  system_prompt: z.string(),
  model: z.string(),
  tools: z.array(z.string()),
  memory_policy: z.string(),
  budget_monthly_usd: z.number(),
  enabled: z.boolean(),
  is_seed: z.boolean(),
  created_at: z.string(),
});
export type AgentDetail = z.infer<typeof AgentDetailSchema>;

export const CatalogToolSchema = z.object({
  name: z.string(),
  label: z.string(),
  description: z.string(),
  approval_gated: z.boolean(),
  memory_tool: z.boolean(),
});
export type CatalogTool = z.infer<typeof CatalogToolSchema>;

export const CatalogGroupSchema = z.object({
  group: z.string(),
  label: z.string(),
  tools: z.array(CatalogToolSchema),
});
export type CatalogGroup = z.infer<typeof CatalogGroupSchema>;

export const CatalogSchema = z.object({
  groups: z.array(CatalogGroupSchema),
  models: z.array(z.string()),
  memory_policies: z.array(z.string()),
});
export type Catalog = z.infer<typeof CatalogSchema>;

export const TemplateSchema = z.object({
  template_id: z.string(),
  name: z.string(),
  summary: z.string(),
  system_prompt: z.string(),
  model: z.string(),
  tools: z.array(z.string()),
  memory_policy: z.string(),
  budget_monthly_usd: z.number(),
});
export type Template = z.infer<typeof TemplateSchema>;

export const TemplateListSchema = z.object({ templates: z.array(TemplateSchema) });
export type TemplateList = z.infer<typeof TemplateListSchema>;

export const SoftDeleteResultSchema = z.object({
  agent_id: z.string(),
  enabled: z.boolean(),
  soft_deleted: z.boolean(),
});

// ─── Channels (Phase D, CHANNELS.md §12) ─────────────────────────────────

/** Platforms the pairing form offers. Matches the agent-cloud PLATFORMS
 * tuple; the API is the authoritative belt. */
export const CHANNEL_PLATFORMS = ["telegram", "googlechat"] as const;
export type ChannelPlatform = (typeof CHANNEL_PLATFORMS)[number];

export const CHANNEL_PLATFORM_LABELS: Record<ChannelPlatform, string> = {
  telegram: "Telegram",
  googlechat: "Google Chat",
};

/** One channel link row (CHANNELS.md §12 list shape). */
export const ChannelLinkSchema = z.object({
  link_id: z.string(),
  platform: z.string(),
  agent_id: z.string(),
  status: z.string(),
  platform_chat_id: z.string().nullable(),
  display_name: z.string().nullable(),
  created_at: z.string(),
  linked_at: z.string().nullable(),
});
export type ChannelLink = z.infer<typeof ChannelLinkSchema>;

export const ChannelLinkListSchema = z.object({
  items: z.array(ChannelLinkSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
});
export type ChannelLinkList = z.infer<typeof ChannelLinkListSchema>;

/** POST /channels/pair response — the freshly minted (pending) link + code. */
export const ChannelPairResultSchema = z.object({
  link_id: z.string(),
  platform: z.string(),
  agent_id: z.string(),
  status: z.string(),
  pairing_code: z.string(),
  expires_at: z.string().nullable(),
  instructions: z.string(),
});
export type ChannelPairResult = z.infer<typeof ChannelPairResultSchema>;

export const ChannelRevokeResultSchema = z.object({
  link_id: z.string(),
  status: z.string(),
});
export type ChannelRevokeResult = z.infer<typeof ChannelRevokeResultSchema>;

export type AgentCreatePayload = {
  agent_id: string;
  system_prompt: string;
  model?: string;
  tools?: string[];
  memory_policy?: string;
  budget_monthly_usd?: number;
  enabled?: boolean;
};

export type AgentPatchPayload = Partial<{
  system_prompt: string;
  model: string;
  tools: string[];
  memory_policy: string;
  budget_monthly_usd: number;
  enabled: boolean;
}>;

/** Pure client-side mirror of the server §4 slug rule — for form UX only; the
 * API is always the authoritative belt. */
export const SLUG_RE = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;

export function validateAgentDraft(
  draft: { agent_id: string; system_prompt: string; budget_monthly_usd: number },
  opts: { tenantCap: number; isEdit: boolean; promptCap?: number },
): string | null {
  const promptCap = opts.promptCap ?? 8000;
  if (!opts.isEdit && !SLUG_RE.test(draft.agent_id)) {
    return "Slug must be lowercase letters/digits and internal hyphens (1–63 chars).";
  }
  if (!draft.system_prompt.trim()) return "System prompt is required.";
  if (draft.system_prompt.length > promptCap) {
    return `System prompt exceeds the ${promptCap}-character limit.`;
  }
  if (!(draft.budget_monthly_usd > 0)) return "Budget must be greater than 0.";
  if (draft.budget_monthly_usd > opts.tenantCap) {
    return `Budget exceeds the workspace cap ($${opts.tenantCap}).`;
  }
  return null;
}

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

async function sendJson<T>(
  method: "POST" | "PATCH" | "DELETE",
  path: string,
  schema: z.ZodType<T>,
  body?: unknown,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
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

// ─── Agent Builder CRUD calls (Phase C) ──────────────────────────────────

function wsQuery(workspace: string): string {
  return workspace && workspace !== "personal"
    ? `?workspace=${encodeURIComponent(workspace)}`
    : "";
}

export function fetchCatalog(workspace = "personal"): Promise<Catalog> {
  return getJson(`/api/v1/agent-cloud/catalog${wsQuery(workspace)}`, CatalogSchema);
}

export function fetchTemplates(workspace = "personal"): Promise<TemplateList> {
  return getJson(
    `/api/v1/agent-cloud/templates${wsQuery(workspace)}`,
    TemplateListSchema,
  );
}

export function fetchAgentDetail(
  agentId: string,
  workspace = "personal",
): Promise<AgentDetail> {
  return getJson(
    `/api/v1/agent-cloud/agents/${encodeURIComponent(agentId)}${wsQuery(workspace)}`,
    AgentDetailSchema,
  );
}

export function createAgent(
  payload: AgentCreatePayload,
  workspace = "personal",
): Promise<AgentDetail> {
  const body =
    workspace && workspace !== "personal" ? { ...payload, workspace } : payload;
  return sendJson("POST", "/api/v1/agent-cloud/agents", AgentDetailSchema, body);
}

export function patchAgent(
  agentId: string,
  payload: AgentPatchPayload,
  workspace = "personal",
): Promise<AgentDetail> {
  const body =
    workspace && workspace !== "personal" ? { ...payload, workspace } : payload;
  return sendJson(
    "PATCH",
    `/api/v1/agent-cloud/agents/${encodeURIComponent(agentId)}`,
    AgentDetailSchema,
    body,
  );
}

export function deleteAgent(agentId: string, workspace = "personal") {
  return sendJson(
    "DELETE",
    `/api/v1/agent-cloud/agents/${encodeURIComponent(agentId)}${wsQuery(workspace)}`,
    SoftDeleteResultSchema,
  );
}

// ─── Query hooks ─────────────────────────────────────────────────────────────

export function useAgentCloudAgents(
  optsOrWorkspace?: string | Partial<UseQueryOptions<AgentCloudAgentList>>,
  maybeOpts?: Partial<UseQueryOptions<AgentCloudAgentList>>,
) {
  // Backward compatible: called as useAgentCloudAgents(opts?) by the
  // assistant page (personal), or useAgentCloudAgents(workspace, opts?) by
  // the builder page (workspace-aware).
  const workspace =
    typeof optsOrWorkspace === "string" ? optsOrWorkspace : "personal";
  const opts =
    typeof optsOrWorkspace === "string" ? maybeOpts : optsOrWorkspace;
  return useQuery<AgentCloudAgentList>({
    queryKey: ["agent-cloud", "agents", workspace],
    queryFn: () =>
      getJson(
        `/api/v1/agent-cloud/agents${wsQuery(workspace)}`,
        AgentCloudAgentListSchema,
      ),
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

export function useAgentCloudCatalog(
  workspace = "personal",
  opts?: Partial<UseQueryOptions<Catalog>>,
) {
  return useQuery<Catalog>({
    queryKey: ["agent-cloud", "catalog", workspace],
    queryFn: () => fetchCatalog(workspace),
    staleTime: 5 * 60_000,
    ...opts,
  });
}

export function useAgentCloudTemplates(
  workspace = "personal",
  opts?: Partial<UseQueryOptions<TemplateList>>,
) {
  return useQuery<TemplateList>({
    queryKey: ["agent-cloud", "templates", workspace],
    queryFn: () => fetchTemplates(workspace),
    staleTime: 5 * 60_000,
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

// ─── Channels calls + hooks (Phase D) ────────────────────────────────────

/** Mint a pairing code for (agent, platform) in the caller's tenant. The
 * bridge injects tenant_id server-side; the client only sends agent_id +
 * platform (+ workspace when org). */
export function pairChannel(
  payload: { agent_id: string; platform: ChannelPlatform },
  workspace = "personal",
): Promise<ChannelPairResult> {
  const body =
    workspace && workspace !== "personal"
      ? { ...payload, workspace }
      : payload;
  return sendJson(
    "POST",
    "/api/v1/agent-cloud/channels/pair",
    ChannelPairResultSchema,
    body,
  );
}

/** Revoke a channel link. 404 (indistinguishable) for unknown/cross-tenant. */
export function revokeChannel(
  linkId: string,
  workspace = "personal",
): Promise<ChannelRevokeResult> {
  return sendJson(
    "POST",
    `/api/v1/agent-cloud/channels/${encodeURIComponent(linkId)}/revoke${wsQuery(
      workspace,
    )}`,
    ChannelRevokeResultSchema,
  );
}

export function useAgentCloudChannels(
  workspace = "personal",
  opts?: Partial<UseQueryOptions<ChannelLinkList>>,
) {
  return useQuery<ChannelLinkList>({
    queryKey: ["agent-cloud", "channels", workspace],
    queryFn: () =>
      getJson(
        `/api/v1/agent-cloud/channels${wsQuery(workspace)}`,
        ChannelLinkListSchema,
      ),
    staleTime: 30_000,
    ...opts,
  });
}

/** Invalidate the channels list after a pair/revoke. */
export function useInvalidateChannels() {
  const qc = useQueryClient();
  return () =>
    void qc.invalidateQueries({ queryKey: ["agent-cloud", "channels"] });
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
  args: {
    agentId: string;
    message: string;
    sessionId?: string | null;
    workspace?: string;
  },
  handlers: SendHandlers,
): Promise<void> {
  const body = JSON.stringify({
    agent_id: args.agentId,
    message: args.message,
    ...(args.sessionId ? { session_id: args.sessionId } : {}),
    ...(args.workspace && args.workspace !== "personal"
      ? { workspace: args.workspace }
      : {}),
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
  args: {
    agentId: string;
    message: string;
    sessionId?: string | null;
    workspace?: string;
  },
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
      ...(args.workspace && args.workspace !== "personal"
        ? { workspace: args.workspace }
        : {}),
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
