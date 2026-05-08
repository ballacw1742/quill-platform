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
  passkey_assertion?: unknown;
};

export function useDecide(opts?: UseMutationOptions<ApprovalItem, Error, DecideInput>) {
  const qc = useQueryClient();
  return useMutation<ApprovalItem, Error, DecideInput>({
    mutationFn: async ({ id, decision, reason, edited_payload }) => {
      if (USE_MOCK) {
        await sleep(180);
        return ApprovalItemSchema.parse(
          mockStore.decide(id, decision, { reason, edited_payload }),
        );
      }
      return apiFetch(`/api/v1/approvals/${id}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision, reason, edited_payload }),
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
