"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationOptions,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { z } from "zod";
import {
  AgentSchema,
  ApprovalItemSchema,
  AuditEntrySchema,
  ChainVerificationSchema,
  HealthSchema,
  SessionSchema,
  type Agent,
  type ApprovalItem,
  type AuditEntry,
  type ChainVerification,
  type Health,
  type Session,
} from "@/lib/schemas";
import { mockStore } from "@/lib/mock/store";

export const USE_MOCK =
  typeof process !== "undefined" && process.env.NEXT_PUBLIC_USE_MOCK !== "0";

const API_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) || "";

class ApiError extends Error {
  constructor(public status: number, msg: string) {
    super(msg);
  }
}

async function apiFetch<T>(
  path: string,
  opts: RequestInit & { schema?: z.ZodType<T> } = {},
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(opts.headers || {}),
    },
    ...opts,
  });
  if (res.status === 401) {
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    throw new ApiError(401, "unauthorized");
  }
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

export function useApprovals(opts?: UseQueryOptions<ApprovalItem[]>) {
  return useQuery<ApprovalItem[]>({
    queryKey: ["approvals"],
    queryFn: async () => {
      if (USE_MOCK) {
        await sleep(120);
        return z.array(ApprovalItemSchema).parse(mockStore.listApprovals());
      }
      return apiFetch("/api/v1/approvals", { schema: z.array(ApprovalItemSchema) });
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
      return apiFetch(`/api/v1/approvals/${id}`, { schema: ApprovalItemSchema });
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
      return apiFetch("/api/v1/audit", { schema: z.array(AuditEntrySchema) });
    },
    ...opts,
  });
}

export function useVerifyChain() {
  return useMutation<ChainVerification, Error, void>({
    mutationFn: async () => {
      if (USE_MOCK) {
        await sleep(400);
        return ChainVerificationSchema.parse(mockStore.verifyChain());
      }
      return apiFetch("/api/v1/audit/verify", {
        method: "POST",
        schema: ChainVerificationSchema,
      });
    },
  });
}

// ─── Agents ───────────────────────────────────────────────────────────────────

export function useAgents() {
  return useQuery<Agent[]>({
    queryKey: ["agents"],
    queryFn: async () => {
      if (USE_MOCK) {
        await sleep(100);
        return z.array(AgentSchema).parse(mockStore.listAgents());
      }
      return apiFetch("/api/v1/agents", { schema: z.array(AgentSchema) });
    },
  });
}

export function useSetTrustTier() {
  const qc = useQueryClient();
  return useMutation<Agent, Error, { agent_id: string; trust_tier: Agent["trust_tier"] }>({
    mutationFn: async ({ agent_id, trust_tier }) => {
      if (USE_MOCK) {
        await sleep(150);
        return AgentSchema.parse(mockStore.setTrustTier(agent_id, trust_tier));
      }
      return apiFetch(`/api/v1/agents/${agent_id}/trust-tier`, {
        method: "POST",
        body: JSON.stringify({ trust_tier }),
        schema: AgentSchema,
      });
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
    queryFn: async () => {
      if (USE_MOCK) {
        await sleep(60);
        return HealthSchema.parse(mockStore.getHealth());
      }
      return apiFetch("/api/v1/health", { schema: HealthSchema });
    },
    refetchInterval: USE_MOCK ? 5000 : 15000,
  });
}

// ─── Auth ─────────────────────────────────────────────────────────────────────

export function useSession() {
  return useQuery<Session | null>({
    queryKey: ["session"],
    queryFn: async () => {
      if (USE_MOCK) {
        await sleep(40);
        return mockStore.getSession();
      }
      try {
        return await apiFetch("/api/v1/auth/session", { schema: SessionSchema });
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 30_000,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation<Session, Error, { email: string; password: string }>({
    mutationFn: async ({ email, password }) => {
      if (USE_MOCK) {
        await sleep(150);
        return SessionSchema.parse(mockStore.login(email, password));
      }
      return apiFetch("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
        schema: SessionSchema,
      });
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
      await apiFetch("/api/v1/auth/logout", { method: "POST" });
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
      return apiFetch("/api/v1/admin/audit/mirror_status");
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
      return apiFetch(`/api/v1/admin/audit/verifications/recent?limit=${limit}`);
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
