"use client";

import * as React from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationOptions,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { toast } from "sonner";
import { z } from "zod";
import {
  AgentSchema,
  ApprovalItemSchema,
  AuditEntrySchema,
  ChainVerificationSchema,
  DocumentDriveLinkSchema,
  DocumentListPageSchema,
  DocumentSchema,
  DocumentSearchResultSchema,
  EstimateListResponseSchema,
  EstimateStatusSchema,
  EstimateUploadResponseSchema,
  StartEstimationResponseSchema,
  HealthSchema,
  SessionSchema,
  isEstimateInFlight,
  type Agent,
  type ApprovalItem,
  type AuditEntry,
  type ChainVerification,
  type Document,
  type DocumentDriveLink,
  type DocumentExportFormat,
  type DocumentListPage,
  type DocumentSearchResult,
  type DocumentSummary,
  type EstimateExportFormat,
  type EstimateStatus,
  type EstimateUploadResponse,
  type StartEstimationResponse,
  type Health,
  type Session,
  DevChatMessageSchema,
  DevChatSendResponseSchema,
  DevChatStatusSchema,
  DevChatThreadPageSchema,
  type DevChatMessage,
  type DevChatSendResponse,
  type DevChatStatus,
  type DevChatThreadPage,
  ContractSchema,
  ContractListPageSchema,
  ContractStatusSchema,
  ContractUploadResponseSchema,
  type Contract,
  type ContractListPage,
  type ContractStatus,
  type ContractUploadResponse,
} from "@/lib/schemas";
import { mockStore } from "@/lib/mock/store";

export const USE_MOCK =
  typeof process !== "undefined" && process.env.NEXT_PUBLIC_USE_MOCK !== "0";

const API_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) || "";

export class ApiError extends Error {
  constructor(public status: number, msg: string) {
    super(msg);
    this.name = "ApiError";
  }
}

function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("quill_session_token");
}

export function setStoredToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem("quill_session_token", token);
  else window.localStorage.removeItem("quill_session_token");
}

async function apiFetch<T>(
  path: string,
  opts: RequestInit & { schema?: z.ZodType<T> } = {},
): Promise<T> {
  const token = getStoredToken();
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts.headers || {}),
    },
    ...opts,
  });
  // Per-hook 401 handling: do NOT auto-redirect from apiFetch. The session
  // hook is responsible for noticing a stale token and clearing it; bouncing on
  // every secondary 401 (e.g. admin endpoints that need a separate gate) was
  // causing the audit/agents/health pages to flap back to /login.
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, text || res.statusText);
  }
  if (res.status === 204) return undefined as unknown as T;
  const data = await res.json();
  return opts.schema ? opts.schema.parse(data) : (data as T);
}

// Small jitter to make mock interactions feel like a real request
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ─── Approvals ────────────────────────────────────────────────────────────────

// Adapter: the API returns a wider, differently-shaped ApprovalItem than the UI
// type. We coerce here so component code stays simple. (Sprint 1.1 vs 1.2
// schema drift — fixed at the fetch boundary; full alignment is a future cleanup.)
function coerceApiApprovalItem(raw: any): ApprovalItem {
  const sources =
    (raw.source_artifacts ?? []).map((s: any) => ({
      kind: s.kind ?? "artifact",
      ref: s.ref ?? s.source_id ?? "",
      excerpt: s.excerpt ?? null,
    }));
  return {
    approval_id: raw.id ?? raw.approval_id,
    agent_id: raw.agent_id,
    agent_version: raw.agent_version ?? "0.1.0",
    agent_model: raw.agent_model ?? undefined,
    prompt_version: raw.agent_prompt_version ?? raw.prompt_version ?? undefined,
    workflow: raw.workflow ?? "",
    // API uses numeric lanes (1=auto, 2=single-sig, 3=dual-sig).
    // UI laneMeta uses tier names. Map: 1->tier-2-auto, 2->tier-1-spotcheck, 3->tier-0-mandatory.
    lane:
      raw.lane === 1
        ? "tier-2-auto"
        : raw.lane === 2
          ? "tier-1-spotcheck"
          : raw.lane === 3
            ? "tier-0-mandatory"
            : typeof raw.lane === "string"
              ? raw.lane
              : "tier-1-spotcheck",
    proposed_action: raw.proposed_action ?? {
      kind: raw.workflow ?? "action",
      target: raw.target_system ?? "unknown",
      api: raw.api_call ?? "",
      payload: raw.payload ?? {},
    },
    context: raw.context ?? {
      project_id: raw.payload?.project_id ?? "QPB1",
      sources,
    },
    confidence: raw.confidence ?? raw.agent_confidence ?? 0,
    rationale: raw.rationale ?? raw.agent_reasoning ?? undefined,
    escalations: raw.escalations ?? [],
    priority:
      raw.priority === "P1-critical"
        ? "critical"
        : raw.priority === "P2-high"
          ? "high"
          : raw.priority === "P4-low"
            ? "low"
            : raw.priority === "high" ||
                raw.priority === "low" ||
                raw.priority === "critical" ||
                raw.priority === "normal"
              ? raw.priority
              : "normal",
    summary: raw.summary ?? undefined,
    status: raw.status ?? "pending",
    created_at: raw.created_at,
    expires_at: raw.expires_at ?? null,
    decided_at: raw.decided_at ?? null,
    decided_by: raw.decided_by ?? null,
    decision_reason: raw.decision_reason ?? null,
  };
}

export function useApprovals(opts?: UseQueryOptions<ApprovalItem[]>) {
  return useQuery<ApprovalItem[]>({
    queryKey: ["approvals"],
    queryFn: async () => {
      if (USE_MOCK) {
        await sleep(120);
        return z.array(ApprovalItemSchema).parse(mockStore.listApprovals());
      }
      // API returns { items, total, limit, offset } — extract items and coerce shape.
      const raw: any = await apiFetch("/api/v1/approvals?limit=200");
      const items = Array.isArray(raw) ? raw : (raw?.items ?? []);
      return items.map(coerceApiApprovalItem);
    },
    refetchInterval: USE_MOCK ? 5000 : 15000,
    ...opts,
  });
}

export function useApproval(id: string, opts?: UseQueryOptions<ApprovalItem | undefined>) {
  return useQuery<ApprovalItem | undefined>({
    queryKey: ["approval", id],
    queryFn: async () => {
      if (USE_MOCK) {
        await sleep(80);
        const item = mockStore.getApproval(id);
        return item ? ApprovalItemSchema.parse(item) : undefined;
      }
      const raw: any = await apiFetch(`/api/v1/approvals/${id}`);
      return coerceApiApprovalItem(raw);
    },
    enabled: !!id,
    ...opts,
  });
}

export type DecideInput = {
  id: string;
  decision: "approved" | "rejected" | "escalated";
  reason?: string;
  edited_payload?: Record<string, unknown>;
  /**
   * The Sprint 2.2 action-assertion JWT minted by
   * `/v1/auth/passkey/challenge/complete`. Required against the live API;
   * the mock store ignores it.
   */
  passkey_assertion?: string;
};

export function useDecide(opts?: UseMutationOptions<ApprovalItem, Error, DecideInput>) {
  const qc = useQueryClient();
  return useMutation<ApprovalItem, Error, DecideInput>({
    mutationFn: async ({ id, decision, reason, edited_payload, passkey_assertion }) => {
      if (USE_MOCK) {
        await sleep(180);
        return ApprovalItemSchema.parse(
          mockStore.decide(id, decision, { reason, edited_payload }),
        );
      }
      // API enum is action-verb (approve|reject|escalate|edit_then_approve);
      // UI internally uses past-tense status form. Map at the wire boundary.
      const wireDecision =
        decision === "approved"
          ? edited_payload
            ? "edit_then_approve"
            : "approve"
          : decision === "rejected"
            ? "reject"
            : "escalate";
      return apiFetch(`/api/v1/approvals/${id}/decide`, {
        method: "POST",
        body: JSON.stringify({
          decision: wireDecision,
          rejection_reason: reason,
          edits: edited_payload,
          auth_assertion: passkey_assertion,
        }),
        schema: ApprovalItemSchema,
      });
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["approvals"] });
      qc.invalidateQueries({ queryKey: ["approval", data.approval_id] });
      qc.invalidateQueries({ queryKey: ["audit"] });
      qc.invalidateQueries({ queryKey: ["health"] });
    },
    onError: (e) => {
      if (e instanceof ApiError) {
        if (e.status === 409) {
          // Item was already decided by another session — refresh and tell user.
          toast.info("Already decided. Refreshing…");
          void qc.invalidateQueries({ queryKey: ["approvals"] });
          return;
        }
        if (e.status === 401) {
          toast.error("Re-authentication required. Try the passkey again.");
          return;
        }
      }
      toast.error("Couldn't save your decision. Try again.");
    },
    ...opts,
  });
}

// ─── Audit ────────────────────────────────────────────────────────────────────

export function useAudit(opts?: UseQueryOptions<AuditEntry[]>) {
  return useQuery<AuditEntry[]>({
    queryKey: ["audit"],
    queryFn: async () => {
      if (USE_MOCK) {
        await sleep(80);
        return z.array(AuditEntrySchema).parse(mockStore.listAudit());
      }
      // API path is /audit/recent, with default limit. Bump to 200 for the audit page.
      const raw: any = await apiFetch("/api/v1/audit/recent?limit=200");
      const items = Array.isArray(raw) ? raw : (raw?.items ?? []);
      return z.array(AuditEntrySchema).parse(items);
    },
    ...opts,
  });
}

export function useVerifyChain() {
  return useMutation<ChainVerification, Error, void>({
    mutationFn: async (): Promise<ChainVerification> => {
      if (USE_MOCK) {
        await sleep(400);
        return ChainVerificationSchema.parse(mockStore.verifyChain()) as ChainVerification;
      }
      // API endpoint is GET, not POST.
      return (await apiFetch("/api/v1/audit/verify", {
        method: "GET",
        schema: ChainVerificationSchema,
      })) as ChainVerification;
    },
  });
}

// ─── Agents ───────────────────────────────────────────────────────────────────

export function useAgents() {
  return useQuery<Agent[]>({
    queryKey: ["agents"],
    queryFn: async (): Promise<Agent[]> => {
      if (USE_MOCK) {
        await sleep(100);
        return z.array(AgentSchema).parse(mockStore.listAgents()) as Agent[];
      }
      return (await apiFetch("/api/v1/agents", { schema: z.array(AgentSchema) })) as Agent[];
    },
  });
}

export function useSetTrustTier() {
  const qc = useQueryClient();
  return useMutation<Agent, Error, { agent_id: string; trust_tier: Agent["trust_tier"] }>({
    mutationFn: async ({ agent_id, trust_tier }): Promise<Agent> => {
      if (USE_MOCK) {
        await sleep(150);
        return AgentSchema.parse(mockStore.setTrustTier(agent_id, trust_tier)) as Agent;
      }
      return (await apiFetch(`/api/v1/agents/${agent_id}/trust-tier`, {
        method: "POST",
        body: JSON.stringify({ trust_tier }),
        schema: AgentSchema,
      })) as Agent;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      qc.invalidateQueries({ queryKey: ["audit"] });
    },
  });
}

/** Sprint DC.4 — Toggle agent enabled/disabled via PATCH /v1/agents/{id}/toggle */
export function useToggleAgent() {
  const qc = useQueryClient();
  return useMutation<Agent, Error, { agent_id: string }>({
    mutationFn: async ({ agent_id }): Promise<Agent> => {
      return (await apiFetch(`/api/v1/agents/${agent_id}/toggle`, {
        method: "PATCH",
        schema: AgentSchema,
      })) as Agent;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents"] });
    },
  });
}

// ─── Health ───────────────────────────────────────────────────────────────────

export function useHealth() {
  return useQuery<Health>({
    queryKey: ["health"],
    queryFn: async (): Promise<Health> => {
      if (USE_MOCK) {
        await sleep(60);
        return HealthSchema.parse(mockStore.getHealth()) as Health;
      }
      // API has /admin/health, not /health.
      return (await apiFetch("/api/v1/admin/health", {
        schema: HealthSchema,
        headers: {
          // The admin gate accepts the user JWT for owner-role users; the
          // shared-secret X-Admin header is the agent path. Both work.
        },
      })) as Health;
    },
    refetchInterval: USE_MOCK ? 5000 : 15000,
  });
}

// ─── Auth ─────────────────────────────────────────────────────────────────────

export function useSession() {
  return useQuery<Session | null>({
    queryKey: ["session"],
    queryFn: async (): Promise<Session | null> => {
      if (USE_MOCK) {
        await sleep(40);
        return mockStore.getSession() as Session | null;
      }
      // No token → no session. Don't even hit the network (also avoids the
      // global 401 redirect short-circuit in apiFetch).
      const token = getStoredToken();
      if (!token) return null;
      try {
        // API exposes /auth/me, not /auth/session. The schema is permissive enough for both.
        return (await apiFetch("/api/v1/auth/me", { schema: SessionSchema })) as Session;
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          // Stale token; clear it.
          setStoredToken(null);
          return null;
        }
        // Any other error (network blip, parse failure): treat as no-session for
        // safety, but don't bounce the user to /login — let them retry.
        // eslint-disable-next-line no-console
        console.error("useSession: unexpected error", e);
        return null;
      }
    },
    staleTime: 30_000,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation<Session, Error, { email: string; password: string }>({
    mutationFn: async ({ email, password }): Promise<Session> => {
      if (USE_MOCK) {
        await sleep(150);
        return SessionSchema.parse(mockStore.login(email, password)) as Session;
      }
      const session = (await apiFetch("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
        schema: SessionSchema,
      })) as Session;
      // Persist the JWT so subsequent requests authenticate.
      if (session.access_token) {
        setStoredToken(session.access_token);
      }
      return session;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["session"] }),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation<void, Error, void>({
    mutationFn: async () => {
      if (USE_MOCK) {
        mockStore.logout();
        return;
      }
      // No server-side logout endpoint; client-side token clear is sufficient for JWT auth.
      // Token is held in localStorage; the apiFetch wrapper will drop it on next mutation.
      if (typeof window !== "undefined") {
        window.localStorage.removeItem("quill_session_token");
      }
    },
    onSuccess: () => qc.setQueryData(["session"], null),
  });
}

// ─── Sprint 2.3 — Audit log resilience (offsite mirror + verification) ────────
export type AuditMirrorStatus = {
  mode: "b2" | "local";
  bucket: string | null;
  queue_depth: number;
  last_mirrored_at: string | null;
  last_mirrored_seq: number | null;
  last_error: string | null;
  failed_entries: Array<Record<string, unknown>>;
  total_mirrored: number;
  total_failed: number;
  lag_seconds: number | null;
};

export function useAuditMirrorStatus() {
  return useQuery<AuditMirrorStatus>({
    queryKey: ["audit", "mirror_status"],
    queryFn: async () => {
      if (USE_MOCK) {
        await sleep(60);
        return {
          mode: "local" as const,
          bucket: null,
          queue_depth: 0,
          last_mirrored_at: new Date(Date.now() - 72_000).toISOString(),
          last_mirrored_seq: 142,
          last_error: null,
          failed_entries: [],
          total_mirrored: 142,
          total_failed: 0,
          lag_seconds: 72,
        };
      }
      try {
        return await apiFetch("/api/v1/admin/audit/mirror_status");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          // Admin endpoint requires X-Admin secret; user JWT can't access.
          // Return a safe placeholder so the audit page doesn't blow up.
          return {
            mode: "local" as const,
            bucket: null,
            queue_depth: 0,
            last_mirrored_at: null,
            last_mirrored_seq: null,
            last_error: null,
            failed_entries: [],
            total_mirrored: 0,
            total_failed: 0,
            lag_seconds: null,
          };
        }
        throw e;
      }
    },
    refetchInterval: 15_000,
  });
}

export type AuditVerificationRow = {
  id: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  scope: string;
  scope_ref: string | null;
  result: string;
  chain_length_postgres: number | null;
  chain_length_mirror: number | null;
  last_hash_postgres: string | null;
  last_hash_mirror: string | null;
  triggered_by: string;
  details: Record<string, unknown>;
};

export function useRecentAuditVerifications(limit = 10) {
  return useQuery<AuditVerificationRow[]>({
    queryKey: ["audit", "verifications", limit],
    queryFn: async () => {
      if (USE_MOCK) {
        await sleep(80);
        return [];
      }
      try {
        return await apiFetch(`/api/v1/admin/audit/verifications/recent?limit=${limit}`);
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          return [];
        }
        throw e;
      }
    },
    refetchInterval: 60_000,
  });
}

export function useTriggerAuditVerify() {
  const qc = useQueryClient();
  return useMutation<{ job_id: string; status: string }, Error, { approval_id?: string } | void>({
    mutationFn: async (vars) => {
      const body = vars && "approval_id" in vars && vars.approval_id ? vars : {};
      if (USE_MOCK) {
        await sleep(120);
        return { job_id: "mock-job", status: "done" };
      }
      return apiFetch("/api/v1/admin/audit/verify_now", {
        method: "POST",
        body: JSON.stringify(body),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["audit", "verifications"] });
      qc.invalidateQueries({ queryKey: ["audit", "mirror_status"] });
    },
  });
}

// ─── Sprint 2.4: Notifications + Scheduler admin hooks ────────────────────────

export type NotificationTestResult = {
  ok: boolean;
  backend: string;
  detail: string | null;
};

export type SentryTestResult = {
  ok: boolean;
  event_id: string;
  exception_event_id: string;
};

export type SchedulerJob = {
  id: string;
  name: string;
  trigger: string;
  next_run_at: string | null;
  source: "bot" | "canonical";
  last_run_at?: string | null;
  last_status?: string | null;
};

export type SchedulerSnapshot = {
  last_heartbeat_at: string | null;
  bot_connected: boolean;
  jobs: SchedulerJob[];
};

export function useTestTelegram() {
  return useMutation<NotificationTestResult, Error, { chat_id: string; text?: string }>({
    mutationFn: async ({ chat_id, text }) => {
      if (USE_MOCK) {
        await sleep(80);
        return { ok: true, backend: "telegram", detail: "mock" };
      }
      const params = new URLSearchParams({ chat_id });
      if (text) params.set("text", text);
      return apiFetch<NotificationTestResult>(
        `/api/v1/admin/notifications/test_telegram?${params.toString()}`,
      );
    },
  });
}

export function useSentryTest() {
  return useMutation<SentryTestResult, Error, { level?: string; message?: string } | void>({
    mutationFn: async (vars) => {
      if (USE_MOCK) {
        await sleep(60);
        return { ok: true, event_id: "mock-evt-1", exception_event_id: "mock-evt-2" };
      }
      const params = new URLSearchParams();
      if (vars && "level" in vars && vars.level) params.set("level", vars.level);
      if (vars && "message" in vars && vars.message) params.set("message", vars.message);
      const qs = params.toString();
      return apiFetch<SentryTestResult>(
        `/api/v1/admin/notifications/sentry_test${qs ? `?${qs}` : ""}`,
      );
    },
  });
}

export function useSchedulerJobs(opts?: UseQueryOptions<SchedulerSnapshot>) {
  return useQuery<SchedulerSnapshot>({
    queryKey: ["scheduler", "jobs"],
    queryFn: async () => {
      if (USE_MOCK) {
        await sleep(80);
        return {
          last_heartbeat_at: new Date().toISOString(),
          bot_connected: true,
          jobs: [
            {
              id: "daily-brief-deliver",
              name: "Daily Brief — Telegram + Drive delivery",
              trigger: "cron(hour=7, minute=0, tz=America/New_York)",
              next_run_at: new Date(Date.now() + 3600_000).toISOString(),
              source: "bot",
            },
          ],
        };
      }
      return apiFetch<SchedulerSnapshot>("/api/v1/admin/scheduler/jobs");
    },
    refetchInterval: 30_000,
    ...opts,
  });
}

// ─── Documents (Phase D) ──────────────────────────────────────────────────────
//
// Backed by `/v1/documents` from feat/documents-service. The web client always
// hits `${API_BASE}/api/v1/...` which next.config.mjs rewrites to `/v1/...`.
//
// `useDocuments`, `useDocument`, `useSearchDocuments` follow the same TanStack
// Query pattern as the Approvals hooks above. `useDocumentExport` is a function
// that returns a download trigger (not a hook) — it's invoked imperatively from
// the export sheet so the user gets a real browser download.
// `useDocumentDriveLink` is a hook so the detail page can render "Open in Drive"
// only once the link is ready.

export type DocumentListParams = {
  artifact_type?: string;
  agent_id?: string;
  q?: string;
  since?: string;
  limit?: number;
  offset?: number;
};

function buildDocsQuery(params: DocumentListParams = {}): string {
  const u = new URLSearchParams();
  if (params.artifact_type) u.set("artifact_type", params.artifact_type);
  if (params.agent_id) u.set("agent_id", params.agent_id);
  if (params.q) u.set("q", params.q);
  if (params.since) u.set("since", params.since);
  u.set("limit", String(params.limit ?? 50));
  u.set("offset", String(params.offset ?? 0));
  return u.toString();
}

export function useDocuments(
  params: DocumentListParams = {},
  opts?: { enabled?: boolean },
) {
  return useQuery<DocumentListPage>({
    queryKey: ["documents", params],
    queryFn: async (): Promise<DocumentListPage> => {
      if (USE_MOCK) {
        await sleep(80);
        return DocumentListPageSchema.parse(mockStore.listDocuments(params));
      }
      const qs = buildDocsQuery(params);
      return (await apiFetch(`/api/v1/documents?${qs}`, {
        schema: DocumentListPageSchema,
      })) as DocumentListPage;
    },
    enabled: opts?.enabled,
  });
}

export function useDocument(
  id: string | null | undefined,
  opts?: UseQueryOptions<Document | undefined>,
) {
  return useQuery<Document | undefined>({
    queryKey: ["document", id],
    queryFn: async (): Promise<Document | undefined> => {
      if (!id) return undefined;
      if (USE_MOCK) {
        await sleep(60);
        const d = mockStore.getDocument(id);
        return d ? (DocumentSchema.parse(d) as Document) : undefined;
      }
      try {
        return (await apiFetch(`/api/v1/documents/${encodeURIComponent(id)}`, {
          schema: DocumentSchema,
        })) as Document;
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return undefined;
        throw e;
      }
    },
    enabled: !!id,
    ...opts,
  });
}

export function useSearchDocuments(
  q: string,
  opts?: UseQueryOptions<DocumentSearchResult>,
) {
  const trimmed = q.trim();
  return useQuery<DocumentSearchResult>({
    queryKey: ["documents", "search", trimmed],
    queryFn: async (): Promise<DocumentSearchResult> => {
      if (!trimmed) return { items: [], total: 0, q: "" };
      if (USE_MOCK) {
        await sleep(80);
        return DocumentSearchResultSchema.parse(
          mockStore.searchDocuments(trimmed),
        );
      }
      const qs = new URLSearchParams({ q: trimmed }).toString();
      return (await apiFetch(`/api/v1/documents/search?${qs}`, {
        schema: DocumentSearchResultSchema,
      })) as DocumentSearchResult;
    },
    enabled: trimmed.length > 0,
    // Keep results around briefly so quickly-typed queries don't flicker.
    staleTime: 5_000,
    ...opts,
  });
}

export function useDocumentDriveLink(
  id: string | null | undefined,
  opts?: UseQueryOptions<DocumentDriveLink>,
) {
  return useQuery<DocumentDriveLink>({
    queryKey: ["document", id, "drive_link"],
    queryFn: async (): Promise<DocumentDriveLink> => {
      if (!id) return { url: null };
      if (USE_MOCK) {
        await sleep(40);
        return DocumentDriveLinkSchema.parse(mockStore.documentDriveLink(id));
      }
      try {
        return (await apiFetch(
          `/api/v1/documents/${encodeURIComponent(id)}/drive_link`,
          { schema: DocumentDriveLinkSchema },
        )) as DocumentDriveLink;
      } catch (e) {
        if (e instanceof ApiError && (e.status === 404 || e.status === 202)) {
          return { url: null, status: "pending" };
        }
        throw e;
      }
    },
    enabled: !!id,
    // Drive uploads are async; refetch every 30s so a "pending" state recovers.
    refetchInterval: (q) => {
      const data = q.state.data;
      if (!data || !data.url) return 30_000;
      return false;
    },
    ...opts,
  });
}

/**
 * Triggers a browser download of an exported document. Returns a no-arg async
 * function the UI can call from a button click handler.
 *
 * In MOCK mode we synthesize the file client-side from the in-memory store; in
 * live mode we call `/v1/documents/{id}/export?format=...` and stream the
 * response into a Blob the browser can save.
 */
export function useDocumentExport(
  id: string | null | undefined,
  format: DocumentExportFormat,
): () => Promise<void> {
  return React.useCallback(async () => {
    if (!id) return;
    if (typeof window === "undefined") return;
    if (USE_MOCK) {
      const out = mockStore.documentExport(id, format);
      if (!out) return;
      const blob = new Blob([out.content], { type: out.mime });
      triggerDownload(blob, out.filename);
      return;
    }
    const token = getStoredToken();
    const res = await fetch(
      `${API_BASE}/api/v1/documents/${encodeURIComponent(id)}/export?format=${format}`,
      {
        credentials: "include",
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      },
    );
    if (!res.ok) {
      throw new ApiError(res.status, (await res.text().catch(() => "")) || res.statusText);
    }
    const blob = await res.blob();
    // Best-effort filename: prefer Content-Disposition, fall back to id.format.
    const cd = res.headers.get("content-disposition") ?? "";
    const m = cd.match(/filename\*?=(?:UTF-8'')?\"?([^;\";]+)\"?/i);
    const filename = m?.[1] ?? `document-${id}.${format}`;
    triggerDownload(blob, filename);
  }, [id, format]);
}

// ─── Estimates (Phase G.2) ───────────────────────────────────────────────────
//
// Routes (live API; rewritten by next.config.mjs from /api/v1 → /v1):
//   POST /v1/estimates/upload                       multipart
//   GET  /v1/estimates/{upload_id}/status
//   POST /v1/estimates/{upload_id}/start_estimation
//   GET  /v1/estimates/{upload_id}/export?format=md|csv|xer|pdf
//
// MOCK mode: a tiny in-memory store on `globalThis` so the upload → status
// progression is exercisable in dev without the API. The mock store is
// intentionally simple — it lives only for the lifetime of the page.

type MockEstimateRecord = EstimateStatus & {
  _phase: number; // 0..N steps through the pipeline
};

function _mockEstimates(): Map<string, MockEstimateRecord> {
  const g = globalThis as unknown as { __quill_mock_estimates?: Map<string, MockEstimateRecord> };
  if (!g.__quill_mock_estimates) g.__quill_mock_estimates = new Map();
  return g.__quill_mock_estimates;
}

function _mockTickStatus(rec: MockEstimateRecord): MockEstimateRecord {
  // Advance through queued → extracting → classifying → awaiting → estimating → done
  const order = [
    "queued",
    "extracting",
    "classifying",
    "awaiting_classification_approval",
    "estimating",
    "awaiting_package_approval",
    "done",
  ];
  rec._phase = Math.min(rec._phase + 1, order.length - 1);
  rec.status = order[rec._phase] as EstimateStatus["status"];
  rec.updated_at = new Date().toISOString();
  if (rec.status === "awaiting_classification_approval" && !rec.classification_artifact_id) {
    rec.classification_artifact_id = `mock-class-${rec.upload_id}`;
  }
  if (rec.status === "done" && !rec.package_artifact_id) {
    rec.package_artifact_id = `mock-pkg-${rec.upload_id}`;
  }
  return rec;
}

export function useEstimateStatus(
  uploadId: string | null | undefined,
  opts?: UseQueryOptions<EstimateStatus | undefined>,
) {
  return useQuery<EstimateStatus | undefined>({
    queryKey: ["estimate", "status", uploadId],
    queryFn: async (): Promise<EstimateStatus | undefined> => {
      if (!uploadId) return undefined;
      if (USE_MOCK) {
        await sleep(80);
        const rec = _mockEstimates().get(uploadId);
        if (!rec) return undefined;
        return EstimateStatusSchema.parse(_mockTickStatus(rec));
      }
      try {
        return (await apiFetch(
          `/api/v1/estimates/${encodeURIComponent(uploadId)}/status`,
          { schema: EstimateStatusSchema },
        )) as EstimateStatus;
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return undefined;
        throw e;
      }
    },
    enabled: !!uploadId,
    // Poll every 4s while the run is in flight; stop on done | failed.
    refetchInterval: (q) => {
      const data = q.state.data;
      if (!data) return 4000;
      if (isEstimateInFlight(data.status)) return 4000;
      return false;
    },
    ...opts,
  });
}

export function useUploadEstimate(
  opts?: UseMutationOptions<
    EstimateUploadResponse,
    Error,
    { files: File[]; project_label?: string; notes?: string }
  >,
) {
  const qc = useQueryClient();
  return useMutation<
    EstimateUploadResponse,
    Error,
    { files: File[]; project_label?: string; notes?: string }
  >({
    mutationFn: async ({ files, project_label, notes }) => {
      if (!files || files.length === 0) {
        throw new Error("Pick at least one drawing file before starting an estimate.");
      }
      if (USE_MOCK) {
        await sleep(180);
        const upload_id = `mock-${Math.random().toString(36).slice(2, 10)}`;
        const total_bytes = files.reduce((n, f) => n + (f.size || 0), 0);
        const rec: MockEstimateRecord = {
          upload_id,
          status: "queued",
          project_label: project_label ?? "",
          notes: notes ?? "",
          uploaded_files: files.map((f) => ({
            filename: f.name,
            kind: kindFromFilename(f.name),
            size_bytes: f.size,
            extraction_status: "pending",
            extraction_summary: "",
            minio_key: null,
          })),
          classification_artifact_id: null,
          package_artifact_id: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          error_message: null,
          _phase: 0,
        };
        _mockEstimates().set(upload_id, rec);
        return EstimateUploadResponseSchema.parse({
          upload_id,
          file_count: files.length,
          total_bytes,
          extraction_started: true,
        });
      }
      const fd = new FormData();
      for (const f of files) fd.append("files", f, f.name);
      fd.append("project_label", project_label ?? "");
      fd.append("notes", notes ?? "");
      const token = getStoredToken();
      const res = await fetch(`${API_BASE}/api/v1/estimates/upload`, {
        method: "POST",
        credentials: "include",
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          // Note: do NOT set Content-Type — the browser supplies the multipart
          // boundary automatically when given a FormData body.
        },
        body: fd,
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new ApiError(res.status, text || res.statusText);
      }
      const data = await res.json();
      return EstimateUploadResponseSchema.parse(data);
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["estimate", "status", data.upload_id] });
    },
    ...opts,
  });
}

export function useStartEstimation(
  uploadId: string,
  opts?: UseMutationOptions<
    StartEstimationResponse,
    Error,
    { passkey_assertion?: string } | void
  >,
) {
  const qc = useQueryClient();
  return useMutation<
    StartEstimationResponse,
    Error,
    { passkey_assertion?: string } | void
  >({
    mutationFn: async (vars) => {
      if (USE_MOCK) {
        await sleep(220);
        const rec = _mockEstimates().get(uploadId);
        if (rec) {
          rec._phase = 4; // estimating
          rec.status = "estimating";
          rec.updated_at = new Date().toISOString();
        }
        return StartEstimationResponseSchema.parse({
          ok: true,
          upload_id: uploadId,
          audit_hash: "mock-hash",
          agent_id: "estimator-scheduler",
        });
      }
      const token = getStoredToken();
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      };
      const passkey =
        vars && "passkey_assertion" in vars ? vars.passkey_assertion : undefined;
      if (passkey) headers["X-Auth-Assertion"] = passkey;
      const res = await fetch(
        `${API_BASE}/api/v1/estimates/${encodeURIComponent(uploadId)}/start_estimation`,
        {
          method: "POST",
          credentials: "include",
          headers,
          body: JSON.stringify({ auth_assertion: passkey ?? null }),
        },
      );
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new ApiError(res.status, text || res.statusText);
      }
      const data = await res.json();
      return StartEstimationResponseSchema.parse(data);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["estimate", "status", uploadId] });
      qc.invalidateQueries({ queryKey: ["approvals"] });
    },
    ...opts,
  });
}

/**
 * Returns a no-arg async function that triggers a browser download of the
 * exported estimate package in the requested format. Mirrors the pattern of
 * `useDocumentExport` so the callsite is a single `onClick={fn}`.
 */
export function useEstimateExport(
  uploadId: string | null | undefined,
  format: EstimateExportFormat,
): () => Promise<void> {
  return React.useCallback(async () => {
    if (!uploadId) return;
    if (typeof window === "undefined") return;
    if (USE_MOCK) {
      const stub = `# Estimate ${uploadId} (mock ${format})\n\nMock export.\n`;
      const blob = new Blob([stub], { type: "text/plain" });
      triggerDownload(blob, `estimate-${uploadId}.${format}`);
      return;
    }
    const token = getStoredToken();
    const res = await fetch(
      `${API_BASE}/api/v1/estimates/${encodeURIComponent(uploadId)}/export?format=${format}`,
      {
        credentials: "include",
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      },
    );
    if (!res.ok) {
      throw new ApiError(
        res.status,
        (await res.text().catch(() => "")) || res.statusText,
      );
    }
    const blob = await res.blob();
    const cd = res.headers.get("content-disposition") ?? "";
    const m = cd.match(/filename\*?=(?:UTF-8'')?\"?([^;\";]+)\"?/i);
    const filename = m?.[1] ?? `estimate-${uploadId}.${format}`;
    triggerDownload(blob, filename);
  }, [uploadId, format]);
}

function kindFromFilename(name: string): string {
  const ext = name.toLowerCase().split(".").pop() ?? "";
  if (["pdf", "ifc", "dxf", "dwg", "rvt"].includes(ext)) return ext;
  return "other";
}

// ─── Estimates list (Phase G.5) ──────────────────────────────────────────────
//
// The /v1/estimates endpoints expose individual upload status by id but no
// list endpoint. The Documents service indexes both artifact types we care
// about — `aace_classification` (interim) and `cost_schedule_package`
// (published) — and stamps `metadata.upload_id` on each. We fetch both
// artifact_type buckets and merge by upload_id into a single row per
// estimate, biased toward the more-final artifact (`cost_schedule_package`
// wins over `aace_classification` when both are present).
//
// This is used by /estimates (the new tab listing) and any other surface
// that needs a quick "how many estimates have I run / are in flight".

export type EstimateListItem = {
  /** upload_id is the stable join key — used as the route param. */
  upload_id: string;
  /** Human-readable label, falls back to the document title. */
  project_label: string;
  /** Best-known status hint:
   *   - "published" — a cost_schedule_package exists
   *   - "classified" — only a classification doc exists (estimate not generated yet)
   *   - "in_flight" — server-side status is queued/extracting/classifying/estimating
   *   - "failed" — extraction or estimation failed
   */
  status_hint: "published" | "classified" | "in_flight" | "failed";
  /** Server-canonical fine-grained status. */
  status: "queued" | "extracting" | "classifying" | "estimating" | "done" | "failed";
  /** AACE class if known. */
  aace_class?: string;
  /** Total dollar amount when published. */
  total_usd?: number | null;
  /** Most recent created_at among the merged docs (ISO-8601). */
  created_at: string;
  /** Document id of the final/published artifact when available, otherwise
   *  the classification doc id. Used to construct the row's tap target. */
  document_id: string;
  /** Document id of the published cost_schedule_package, if any. */
  package_document_id: string | null;
  /** Document id of the aace_classification doc, if any. */
  classification_document_id: string | null;
  /** Error message when status === "failed". */
  error_message?: string | null;
};

export type EstimateListResult = {
  items: EstimateListItem[];
  /** Sum of the two underlying queries' totals (best-effort; not exact). */
  total: number;
};

export function useListEstimates(opts?: { enabled?: boolean }) {
  return useQuery<EstimateListResult>({
    queryKey: ["estimates", "list"],
    enabled: opts?.enabled ?? true,
    queryFn: async () => {
      const raw: any = await apiFetch("/api/v1/estimates?limit=100");
      const parsed = EstimateListResponseSchema.parse(raw);
      const items: EstimateListItem[] = parsed.items.map((est) => {
        const status_hint: EstimateListItem["status_hint"] =
          est.status === "done"
            ? est.package_artifact_id
              ? "published"
              : "classified"
            : est.status === "failed"
              ? "failed"
              : "in_flight";
        return {
          upload_id: est.upload_id,
          project_label: est.project_label || "Untitled estimate",
          status_hint,
          status: est.status as EstimateListItem["status"],
          aace_class: undefined,
          total_usd: null,
          created_at: est.created_at,
          // Best-effort tap target: package > classification > /estimates/[upload_id]
          document_id:
            est.package_artifact_id ??
            est.classification_artifact_id ??
            est.upload_id,
          package_document_id: est.package_artifact_id ?? null,
          classification_document_id: est.classification_artifact_id ?? null,
          error_message: est.error_message ?? null,
        };
      });
      return {
        items,
        total: parsed.total,
      };
    },
    refetchInterval: (query) => {
      // Poll while any item is in flight.
      const data = (query.state.data as EstimateListResult | undefined) ?? null;
      if (!data) return false;
      const inFlight = data.items.some((it) => it.status_hint === "in_flight");
      return inFlight ? 5000 : false;
    },
  });
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Slight delay before revoke so the browser can start the download.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ─── Dev Chat (Sprint DC.1) ──────────────────────────────────────────────────
// (DevChat schema imports hoisted to the top-level import block above.)

export function useDevChatThread(opts?: { before?: string; limit?: number }) {
  const params = new URLSearchParams();
  if (opts?.before) params.set("before", opts.before);
  if (opts?.limit) params.set("limit", String(opts.limit));
  const qs = params.toString();

  return useQuery<DevChatThreadPage>({
    queryKey: ["dev-chat", "thread", qs],
    queryFn: () =>
      apiFetch(`/api/v1/dev-chat/thread${qs ? "?" + qs : ""}`, {
        schema: DevChatThreadPageSchema,
      }),
    staleTime: 10_000,
  });
}

export function useDevChatStatus() {
  return useQuery<DevChatStatus>({
    queryKey: ["dev-chat", "status"],
    queryFn: () =>
      apiFetch("/api/v1/dev-chat/status", { schema: DevChatStatusSchema }),
    refetchInterval: 5_000,
  });
}

export function useDevChatSend() {
  const qc = useQueryClient();
  return useMutation<DevChatSendResponse, Error, { content: string; auth_assertion?: string }>({
    mutationFn: ({ content, auth_assertion }) =>
      apiFetch("/api/v1/dev-chat/messages", {
        method: "POST",
        body: JSON.stringify({ content, auth_assertion: auth_assertion ?? "" }),
        schema: DevChatSendResponseSchema,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dev-chat"] });
    },
  });
}

export function useDevChatCancel() {
  const qc = useQueryClient();
  return useMutation<DevChatStatus, Error, { task_id: string; auth_assertion?: string }>({
    mutationFn: ({ task_id, auth_assertion }) =>
      apiFetch(`/api/v1/dev-chat/cancel/${task_id}`, {
        method: "POST",
        body: JSON.stringify({ auth_assertion: auth_assertion ?? "" }),
        schema: DevChatStatusSchema,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dev-chat"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Contracts (Sprint Contracts.1)
// ---------------------------------------------------------------------------

/** GET /v1/contracts — list with optional filters. */
export function useContractsList(
  params?: { status?: string; contract_type?: string; source?: string; limit?: number; offset?: number },
  opts?: UseQueryOptions<ContractListPage | undefined>,
) {
  return useQuery<ContractListPage | undefined>({
    queryKey: ["contracts", "list", params],
    queryFn: async (): Promise<ContractListPage | undefined> => {
      const qp = new URLSearchParams();
      if (params?.status) qp.set("status", params.status);
      if (params?.contract_type) qp.set("contract_type", params.contract_type);
      if (params?.source) qp.set("source", params.source);
      if (params?.limit != null) qp.set("limit", String(params.limit));
      if (params?.offset != null) qp.set("offset", String(params.offset));
      const qs = qp.toString() ? `?${qp.toString()}` : "";
      return apiFetch(`/api/v1/contracts${qs}`, { schema: ContractListPageSchema });
    },
    ...opts,
  });
}

/** GET /v1/contracts/{upload_id} — full record. */
export function useContract(
  uploadId: string | null | undefined,
  opts?: UseQueryOptions<Contract | undefined>,
) {
  return useQuery<Contract | undefined>({
    queryKey: ["contracts", "detail", uploadId],
    queryFn: async (): Promise<Contract | undefined> => {
      if (!uploadId) return undefined;
      try {
        return await apiFetch(`/api/v1/contracts/${encodeURIComponent(uploadId)}`, {
          schema: ContractSchema,
        });
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return undefined;
        throw e;
      }
    },
    enabled: !!uploadId,
    refetchInterval: (q) => {
      const data = q.state.data;
      if (!data) return 4000;
      const inFlight = ["uploaded", "extracting"];
      if (inFlight.includes(data.status)) return 4000;
      return false;
    },
    ...opts,
  });
}

/** POST /v1/contracts/upload — multipart upload. */
export function useUploadContract(
  opts?: UseMutationOptions<
    ContractUploadResponse,
    Error,
    { files: File[]; project_label?: string; contract_type?: string; notes?: string }
  >,
) {
  const qc = useQueryClient();
  return useMutation<
    ContractUploadResponse,
    Error,
    { files: File[]; project_label?: string; contract_type?: string; notes?: string }
  >({
    mutationFn: async ({ files, project_label, contract_type, notes }) => {
      if (!files || files.length === 0) {
        throw new Error("Pick at least one contract file.");
      }
      const fd = new FormData();
      for (const f of files) fd.append("files", f);
      if (project_label) fd.append("project_label", project_label);
      if (contract_type) fd.append("contract_type", contract_type);
      if (notes) fd.append("notes", notes);
      return apiFetch("/api/v1/contracts/upload", {
        method: "POST",
        body: fd,
        schema: ContractUploadResponseSchema,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["contracts"] });
    },
    ...opts,
  });
}

/** POST /v1/contracts/{upload_id}/dispatch_extraction */
export function useDispatchContractExtraction(
  opts?: UseMutationOptions<{ ok: boolean; upload_id: string; audit_hash: string }, Error, { uploadId: string }>,
) {
  const qc = useQueryClient();
  return useMutation<{ ok: boolean; upload_id: string; audit_hash: string }, Error, { uploadId: string }>({
    mutationFn: ({ uploadId }) =>
      apiFetch(`/api/v1/contracts/${encodeURIComponent(uploadId)}/dispatch_extraction`, {
        method: "POST",
      }),
    onSuccess: (_data, { uploadId }) => {
      qc.invalidateQueries({ queryKey: ["contracts", "detail", uploadId] });
      qc.invalidateQueries({ queryKey: ["contracts", "list"] });
    },
    ...opts,
  });
}

/** POST /v1/contracts/{upload_id}/cancel */
export function useCancelContract(
  opts?: UseMutationOptions<{ ok: boolean; upload_id: string }, Error, { uploadId: string; reason?: string }>,
) {
  const qc = useQueryClient();
  return useMutation<{ ok: boolean; upload_id: string }, Error, { uploadId: string; reason?: string }>({
    mutationFn: ({ uploadId, reason }) => {
      const fd = new FormData();
      if (reason) fd.append("reason", reason);
      return apiFetch(`/api/v1/contracts/${encodeURIComponent(uploadId)}/cancel`, {
        method: "POST",
        body: fd,
      });
    },
    onSuccess: (_data, { uploadId }) => {
      qc.invalidateQueries({ queryKey: ["contracts", "detail", uploadId] });
      qc.invalidateQueries({ queryKey: ["contracts", "list"] });
    },
    ...opts,
  });
}

// ─── Contracts Review + Interpretation (Sprint Contracts.2) ──────────────────

import type {
  ContractReview,
  ContractReviewListResponse,
  ContractInterpretation,
  ContractInterpretationListResponse,
} from "@/lib/schemas";
import {
  ContractReviewSchema,
  ContractReviewListResponseSchema,
  ContractInterpretationSchema,
  ContractInterpretationListResponseSchema,
} from "@/lib/schemas";

/** POST /v1/contracts/{upload_id}/dispatch_review — passkey-gated */
export function useDispatchContractReview(
  uploadId: string,
  opts?: UseMutationOptions<
    { ok: boolean; upload_id: string; audit_hash: string },
    Error,
    { passkey_assertion?: string } | void
  >,
) {
  const qc = useQueryClient();
  return useMutation<
    { ok: boolean; upload_id: string; audit_hash: string },
    Error,
    { passkey_assertion?: string } | void
  >({
    mutationFn: async (vars) => {
      const passkey =
        vars && "passkey_assertion" in vars ? vars.passkey_assertion : undefined;
      const headers: Record<string, string> = {};
      if (passkey) headers["X-Auth-Assertion"] = passkey;
      return apiFetch(
        `/api/v1/contracts/${encodeURIComponent(uploadId)}/dispatch_review`,
        { method: "POST", headers },
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["contracts", "detail", uploadId] });
      qc.invalidateQueries({ queryKey: ["contracts", "reviews", uploadId] });
    },
    ...opts,
  });
}

/** POST /v1/contracts/{upload_id}/interpret — passkey-gated, optimistic append */
export function useInterpretContract(
  uploadId: string,
  opts?: UseMutationOptions<
    ContractInterpretation,
    Error,
    { question: string; passkey_assertion?: string }
  >,
) {
  const qc = useQueryClient();
  return useMutation<
    ContractInterpretation,
    Error,
    { question: string; passkey_assertion?: string }
  >({
    mutationFn: async ({ question, passkey_assertion }) => {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (passkey_assertion) headers["X-Auth-Assertion"] = passkey_assertion;
      return apiFetch(
        `/api/v1/contracts/${encodeURIComponent(uploadId)}/interpret`,
        {
          method: "POST",
          headers,
          body: JSON.stringify({ question }),
          schema: ContractInterpretationSchema,
        },
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ["contracts", "interpretations", uploadId],
      });
    },
    ...opts,
  });
}

/** GET /v1/contracts/{upload_id}/reviews */
export function useContractReviews(
  uploadId: string,
  opts?: UseQueryOptions<ContractReviewListResponse | undefined>,
) {
  return useQuery<ContractReviewListResponse | undefined>({
    queryKey: ["contracts", "reviews", uploadId],
    queryFn: async (): Promise<ContractReviewListResponse | undefined> => {
      if (!uploadId) return undefined;
      return apiFetch(
        `/api/v1/contracts/${encodeURIComponent(uploadId)}/reviews`,
        { schema: ContractReviewListResponseSchema },
      );
    },
    enabled: !!uploadId,
    ...opts,
  });
}

/** GET /v1/contracts/{upload_id}/interpretations */
export function useContractInterpretations(
  uploadId: string,
  opts?: UseQueryOptions<ContractInterpretationListResponse | undefined>,
) {
  return useQuery<ContractInterpretationListResponse | undefined>({
    queryKey: ["contracts", "interpretations", uploadId],
    queryFn: async (): Promise<ContractInterpretationListResponse | undefined> => {
      if (!uploadId) return undefined;
      return apiFetch(
        `/api/v1/contracts/${encodeURIComponent(uploadId)}/interpretations`,
        { schema: ContractInterpretationListResponseSchema },
      );
    },
    enabled: !!uploadId,
    ...opts,
  });
}

// ---------------------------------------------------------------------------
// Contracts.3 — Drafter hooks
// ---------------------------------------------------------------------------
import {
  ContractTemplate,
  ContractTemplateListResponse,
  ContractDraftRequest,
  ContractDraft,
  ContractTemplateSchema,
  ContractTemplateListResponseSchema,
  ContractDraftMetadataSchema,
  ContractDraftSchema,
} from "@/lib/schemas";

/** GET /v1/contracts/templates — list all available templates */
export function useContractTemplates(
  opts?: UseQueryOptions<ContractTemplateListResponse | undefined>,
) {
  return useQuery<ContractTemplateListResponse | undefined>({
    queryKey: ["contracts", "templates"],
    queryFn: async (): Promise<ContractTemplateListResponse | undefined> => {
      return apiFetch("/api/v1/contracts/templates", {
        schema: ContractTemplateListResponseSchema,
      });
    },
    ...opts,
  });
}

/** GET /v1/contracts/templates/{templateId} — single template detail */
export function useContractTemplate(
  templateId: string | null | undefined,
  opts?: UseQueryOptions<ContractTemplate | undefined>,
) {
  return useQuery<ContractTemplate | undefined>({
    queryKey: ["contracts", "templates", templateId],
    queryFn: async (): Promise<ContractTemplate | undefined> => {
      if (!templateId) return undefined;
      try {
        return apiFetch(
          `/api/v1/contracts/templates/${encodeURIComponent(templateId)}`,
          { schema: ContractTemplateSchema },
        );
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return undefined;
        throw e;
      }
    },
    enabled: !!templateId,
    ...opts,
  });
}

/** POST /v1/contracts/draft — create a new draft contract request */
export function useCreateContractDraft(
  opts?: UseMutationOptions<
    Record<string, unknown>,
    Error,
    ContractDraftRequest
  >,
) {
  const qc = useQueryClient();
  return useMutation<Record<string, unknown>, Error, ContractDraftRequest>({
    mutationFn: async (body) =>
      apiFetch("/api/v1/contracts/draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["contracts"] });
    },
    ...opts,
  });
}

/** POST /v1/contracts/{uploadId}/redraft — create a revised draft */
export function useRedraftContract(
  uploadId: string,
  opts?: UseMutationOptions<
    Record<string, unknown>,
    Error,
    { revision_notes: string; key_terms_overrides?: Array<Record<string, string>> }
  >,
) {
  const qc = useQueryClient();
  return useMutation<
    Record<string, unknown>,
    Error,
    { revision_notes: string; key_terms_overrides?: Array<Record<string, string>> }
  >({
    mutationFn: async (body) =>
      apiFetch(`/api/v1/contracts/${encodeURIComponent(uploadId)}/redraft`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["contracts"] });
      qc.invalidateQueries({ queryKey: ["contracts", "detail", uploadId] });
    },
    ...opts,
  });
}

/** POST /v1/contracts/{uploadId}/dispatch_draft — trigger the drafter daemon */
export function useDispatchContractDraft(
  uploadId: string,
  opts?: UseMutationOptions<
    { ok: boolean; upload_id: string; audit_hash: string },
    Error,
    void
  >,
) {
  const qc = useQueryClient();
  return useMutation<
    { ok: boolean; upload_id: string; audit_hash: string },
    Error,
    void
  >({
    mutationFn: async () =>
      apiFetch(
        `/api/v1/contracts/${encodeURIComponent(uploadId)}/dispatch_draft`,
        { method: "POST" },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["contracts", "detail", uploadId] });
    },
    ...opts,
  });
}

/** Composite hook: reads draft_artifact_id from contract, fetches the Document */
export function useContractDraft(uploadId: string) {
  const contractQuery = useContract(uploadId);
  const contractData = contractQuery.data as
    | (Record<string, unknown> & { draft_artifact_id?: string | null })
    | undefined;
  const draftArtifactId = contractData?.draft_artifact_id ?? null;

  const documentQuery = useDocument(draftArtifactId);
  const rawDoc = documentQuery.data;

  // Parse the document's metadata field as ContractDraftMetadata
  let draftArtifact: ContractDraft | undefined;
  if (rawDoc) {
    const meta = (rawDoc as Record<string, unknown>).metadata ?? {};
    const payload = {
      ...(meta as Record<string, unknown>),
      artifact_type: "contract_draft",
      artifact_id: rawDoc.id,
      title: rawDoc.title ?? "",
      summary: rawDoc.summary ?? "",
      body_markdown: rawDoc.body_markdown ?? "",
    };
    const parsed = ContractDraftSchema.safeParse(payload);
    if (parsed.success) {
      draftArtifact = parsed.data;
    }
  }

  return {
    isLoading: contractQuery.isLoading || documentQuery.isLoading,
    isError: contractQuery.isError || documentQuery.isError,
    draftArtifact,
    draftArtifactId,
    contractQuery,
    documentQuery,
  };
}

// ---------------------------------------------------------------------------
// Project Requests (Requests tab)
// ---------------------------------------------------------------------------
import {
  ProjectRequestSchema,
  ProjectRequestListResponseSchema,
  ProjectRequestSubmitResponseSchema,
  type ProjectRequest,
  type ProjectRequestListResponse,
  type ProjectRequestSubmitResponse,
} from "@/lib/schemas";

/** GET /v1/requests — list request history for the current user */
export function useProjectRequests(
  opts?: UseQueryOptions<ProjectRequestListResponse | undefined>,
) {
  return useQuery<ProjectRequestListResponse | undefined>({
    queryKey: ["requests"],
    queryFn: async (): Promise<ProjectRequestListResponse | undefined> => {
      return apiFetch("/api/v1/requests", {
        schema: ProjectRequestListResponseSchema,
      });
    },
    refetchInterval: 5000, // Poll every 5s while processing
    ...opts,
  });
}

/** GET /v1/requests/{id} — single request detail */
export function useProjectRequest(
  id: string | null | undefined,
  opts?: UseQueryOptions<ProjectRequest | undefined>,
) {
  return useQuery<ProjectRequest | undefined>({
    queryKey: ["requests", id],
    queryFn: async (): Promise<ProjectRequest | undefined> => {
      if (!id) return undefined;
      return apiFetch(`/api/v1/requests/${encodeURIComponent(id)}`, {
        schema: ProjectRequestSchema,
      });
    },
    enabled: !!id,
    ...opts,
  });
}

/** POST /v1/requests — submit a new project request */
export function useSubmitProjectRequest(
  opts?: UseMutationOptions<
    ProjectRequestSubmitResponse,
    Error,
    FormData
  >,
) {
  const qc = useQueryClient();
  return useMutation<ProjectRequestSubmitResponse, Error, FormData>({
    mutationFn: async (body: FormData) => {
      const token = getStoredToken();
      const headers: Record<string, string> = {};
      if (token) headers["Authorization"] = `Bearer ${token}`;
      const resp = await fetch(`${API_BASE}/api/v1/requests`, {
        method: "POST",
        headers,
        body,
      });
      if (!resp.ok) {
        const text = await resp.text().catch(() => resp.statusText);
        throw new ApiError(resp.status, text);
      }
      const json = await resp.json();
      return ProjectRequestSubmitResponseSchema.parse(json);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["requests"] });
    },
    ...opts,
  });
}

// ---------------------------------------------------------------------------
// Sites (DataSite Intelligence proxy)
// ---------------------------------------------------------------------------
import {
  SiteSchema,
  SiteListResponseSchema,
  ProjectSchema,
  ProjectListResponseSchema,
  ProjectCreateSchema,
  type Site,
  type SiteListResponse,
  type QuillProject,
  type ProjectListResponse,
  type ProjectCreate,
} from "@/lib/schemas";

/** GET /v1/sites — list all site evaluations */
export function useSites(opts?: UseQueryOptions<Site[]>) {
  return useQuery<Site[]>({
    queryKey: ["sites"],
    queryFn: async (): Promise<Site[]> => {
      const raw: any = await apiFetch("/api/v1/sites");
      // Backend may return {items: [...]} or a flat array
      const arr = Array.isArray(raw) ? raw : (raw?.items ?? []);
      return arr;
    },
    refetchInterval: 15000,
    ...opts,
  });
}

/** GET /v1/sites/{id} — single site */
export function useSite(
  id: string | null | undefined,
  opts?: UseQueryOptions<Site | undefined>,
) {
  return useQuery<Site | undefined>({
    queryKey: ["sites", id],
    queryFn: async (): Promise<Site | undefined> => {
      if (!id) return undefined;
      return apiFetch(`/api/v1/sites/${encodeURIComponent(id)}`, {
        schema: SiteSchema,
      });
    },
    enabled: !!id,
    ...opts,
  });
}

/** POST /v1/sites — create a new site */
export function useCreateSite(
  opts?: UseMutationOptions<Site, Error, Record<string, any>>,
) {
  const qc = useQueryClient();
  return useMutation<Site, Error, Record<string, any>>({
    mutationFn: async (body) => {
      return apiFetch("/api/v1/sites", {
        method: "POST",
        body: JSON.stringify(body),
        schema: SiteSchema,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sites"] });
    },
    ...opts,
  });
}

/** POST /v1/sites/questionnaire — submit questionnaire */
export function useSubmitSiteQuestionnaire(
  opts?: UseMutationOptions<Site, Error, Record<string, any>>,
) {
  const qc = useQueryClient();
  return useMutation<Site, Error, Record<string, any>>({
    mutationFn: async (body) => {
      const token = getStoredToken();
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = `Bearer ${token}`;
      const resp = await fetch(`${API_BASE}/api/v1/sites`, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const text = await resp.text().catch(() => resp.statusText);
        throw new ApiError(resp.status, text);
      }
      const json = await resp.json();
      return SiteSchema.parse(json);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sites"] });
    },
    ...opts,
  });
}

/** POST /v1/sites/{id}/run — trigger evaluation */
export function useRunSiteEvaluation(
  opts?: UseMutationOptions<Site, Error, string>,
) {
  const qc = useQueryClient();
  return useMutation<Site, Error, string>({
    mutationFn: async (siteId: string) => {
      return apiFetch(`/api/v1/sites/${encodeURIComponent(siteId)}/run`, {
        method: "POST",
        body: "{}",
      });
    },
    onSuccess: (_, siteId) => {
      qc.invalidateQueries({ queryKey: ["sites", siteId] });
      qc.invalidateQueries({ queryKey: ["sites"] });
    },
    ...opts,
  });
}

// ---------------------------------------------------------------------------
// Projects
// ---------------------------------------------------------------------------

/** GET /v1/projects — list projects for current user */
export function useProjects(opts?: UseQueryOptions<ProjectListResponse | undefined>) {
  return useQuery<ProjectListResponse | undefined>({
    queryKey: ["projects"],
    queryFn: async (): Promise<ProjectListResponse | undefined> => {
      return apiFetch("/api/v1/projects", {
        schema: ProjectListResponseSchema,
      });
    },
    refetchInterval: 15000,
    ...opts,
  });
}

/** GET /v1/projects/{id} — single project */
export function useProject(
  id: string | null | undefined,
  opts?: UseQueryOptions<QuillProject | undefined>,
) {
  return useQuery<QuillProject | undefined>({
    queryKey: ["projects", id],
    queryFn: async (): Promise<QuillProject | undefined> => {
      if (!id) return undefined;
      return apiFetch(`/api/v1/projects/${encodeURIComponent(id)}`, {
        schema: ProjectSchema,
      });
    },
    enabled: !!id,
    ...opts,
  });
}

/** POST /v1/projects — create a project */
export function useCreateProject(
  opts?: UseMutationOptions<QuillProject, Error, ProjectCreate>,
) {
  const qc = useQueryClient();
  return useMutation<QuillProject, Error, ProjectCreate>({
    mutationFn: async (body: ProjectCreate) => {
      return apiFetch("/api/v1/projects", {
        method: "POST",
        body: JSON.stringify(body),
        schema: ProjectSchema,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
    ...opts,
  });
}

/** PATCH /v1/projects/{id} — update phase / status / notes */
export function useUpdateProject(
  opts?: UseMutationOptions<
    QuillProject,
    Error,
    { id: string; body: { phase?: string; status?: string; notes?: string; advance_phase?: boolean } }
  >,
) {
  const qc = useQueryClient();
  return useMutation<
    QuillProject,
    Error,
    { id: string; body: { phase?: string; status?: string; notes?: string; advance_phase?: boolean } }
  >({
    mutationFn: async ({ id, body }) => {
      return apiFetch(`/api/v1/projects/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: JSON.stringify(body),
        schema: ProjectSchema,
      });
    },
    onSuccess: (_, { id }) => {
      qc.invalidateQueries({ queryKey: ["projects", id] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
    ...opts,
  });
}
