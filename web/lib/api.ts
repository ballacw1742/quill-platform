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
      return apiFetch(`/api/v1/approvals/${id}/decision`, {
        method: "POST",
        body: JSON.stringify({
          decision,
          reason,
          edited_payload,
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
  /** Best-known status hint — "published" if a package exists, otherwise
   *  "classified" if only a classification doc exists. The /estimates page
   *  hydrates a finer-grained status with useEstimateStatus per row when
   *  the row is in flight. */
  status_hint: "published" | "classified";
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
};

export type EstimateListResult = {
  items: EstimateListItem[];
  /** Sum of the two underlying queries' totals (best-effort; not exact). */
  total: number;
};

export function useListEstimates(opts?: { enabled?: boolean }) {
  const classifications = useDocuments(
    { artifact_type: "aace_classification", limit: 100 },
    { enabled: opts?.enabled },
  );
  const packages = useDocuments(
    { artifact_type: "cost_schedule_package", limit: 100 },
    { enabled: opts?.enabled },
  );

  const data: EstimateListResult | undefined = React.useMemo(() => {
    if (!classifications.data && !packages.data) return undefined;
    const byUpload = new Map<string, EstimateListItem>();

    const ingest = (
      doc: DocumentSummary,
      kind: "classification" | "package",
    ) => {
      const meta = (doc.metadata ?? {}) as Record<string, unknown>;
      const uploadId =
        (typeof meta.upload_id === "string" && meta.upload_id) ||
        // Fall back to the artifact_id when the API didn't surface it.
        doc.artifact_id;
      if (!uploadId) return;
      const existing = byUpload.get(uploadId);
      const aaceClass =
        (typeof meta.class === "string" && (meta.class as string)) ||
        (typeof meta.aace_class === "string" && (meta.aace_class as string)) ||
        existing?.aace_class;
      const headlineMetrics =
        (meta.headline_metrics as { total_usd?: number | null } | undefined) ??
        undefined;
      const totalUsd =
        (typeof headlineMetrics?.total_usd === "number"
          ? headlineMetrics.total_usd
          : undefined) ?? existing?.total_usd ?? null;

      // Bias: package wins for status / project_label when both exist.
      const isPackageWinning = kind === "package";
      const projectLabel =
        (typeof meta.project_label === "string" &&
          (meta.project_label as string)) ||
        doc.title ||
        existing?.project_label ||
        "Untitled estimate";

      const merged: EstimateListItem = {
        upload_id: uploadId,
        project_label:
          isPackageWinning || !existing
            ? projectLabel
            : existing.project_label,
        status_hint: kind === "package" || existing?.status_hint === "published"
          ? "published"
          : "classified",
        aace_class: aaceClass,
        total_usd: totalUsd,
        // Newest created_at wins; both are ISO-8601 so lexical compare is fine.
        created_at:
          existing && existing.created_at > doc.created_at
            ? existing.created_at
            : doc.created_at,
        document_id:
          kind === "package"
            ? doc.id
            : existing?.package_document_id ?? doc.id,
        package_document_id:
          kind === "package" ? doc.id : existing?.package_document_id ?? null,
        classification_document_id:
          kind === "classification"
            ? doc.id
            : existing?.classification_document_id ?? null,
      };
      byUpload.set(uploadId, merged);
    };

    for (const d of classifications.data?.items ?? []) ingest(d, "classification");
    for (const d of packages.data?.items ?? []) ingest(d, "package");

    const items = Array.from(byUpload.values()).sort((a, b) =>
      a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0,
    );
    return { items, total: items.length };
  }, [classifications.data, packages.data]);

  return {
    data,
    isLoading: classifications.isLoading || packages.isLoading,
    error: classifications.error || packages.error,
    refetch: async () => {
      await Promise.all([classifications.refetch(), packages.refetch()]);
    },
    dataUpdatedAt: Math.max(
      classifications.dataUpdatedAt ?? 0,
      packages.dataUpdatedAt ?? 0,
    ),
  };
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
