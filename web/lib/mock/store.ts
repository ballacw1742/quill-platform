// Tiny in-memory mock store. Used when NEXT_PUBLIC_USE_MOCK=1.
// Mutations resolve in-process so the UI exercises the full happy path
// (approve → item leaves queue → appears in audit) before the real API lands.

import {
  MOCK_AGENTS,
  MOCK_APPROVALS,
  MOCK_AUDIT,
  MOCK_CHAIN,
  MOCK_HEALTH,
  MOCK_SESSION,
} from "@/lib/mock/fixtures";
import type {
  Agent,
  ApprovalItem,
  ApprovalStatus,
  AuditEntry,
  ChainVerification,
  Health,
  Session,
} from "@/lib/schemas";

type Listener = () => void;

class MockStore {
  approvals: ApprovalItem[] = JSON.parse(JSON.stringify(MOCK_APPROVALS));
  agents: Agent[] = JSON.parse(JSON.stringify(MOCK_AGENTS));
  audit: AuditEntry[] = JSON.parse(JSON.stringify(MOCK_AUDIT));
  chain: ChainVerification = { ...MOCK_CHAIN };
  health: Health = JSON.parse(JSON.stringify(MOCK_HEALTH));
  session: Session | null = null;
  private listeners = new Set<Listener>();

  subscribe(l: Listener) {
    this.listeners.add(l);
    return () => this.listeners.delete(l);
  }

  private emit() {
    this.listeners.forEach((l) => l());
  }

  login(email: string, password: string): Session {
    if (!email || !password) throw new Error("missing credentials");
    this.session = { ...MOCK_SESSION, email };
    return this.session;
  }
  logout() {
    this.session = null;
  }
  getSession(): Session | null {
    return this.session;
  }
  ensureSession(): Session {
    if (!this.session) this.session = { ...MOCK_SESSION };
    return this.session;
  }

  listApprovals(): ApprovalItem[] {
    return this.approvals.filter((a) => a.status === "pending");
  }
  getApproval(id: string): ApprovalItem | undefined {
    return this.approvals.find((a) => a.approval_id === id);
  }

  decide(
    id: string,
    decision: "approved" | "rejected" | "escalated",
    opts: { reason?: string; edited_payload?: Record<string, unknown> } = {},
  ) {
    const item = this.approvals.find((a) => a.approval_id === id);
    if (!item) throw new Error("not found");
    if (decision === "approved") {
      if (opts.edited_payload) item.proposed_action.payload = opts.edited_payload;
      item.status = "approved";
    } else if (decision === "rejected") {
      item.status = "rejected";
      item.decision_reason = opts.reason || null;
    } else if (decision === "escalated") {
      item.status = "escalated";
      item.lane = "tier-0-mandatory";
      item.decision_reason = opts.reason || null;
    }
    item.decided_at = new Date().toISOString();
    item.decided_by = this.ensureSession().user_id;

    this.appendAudit({
      action: `approval.${decision}`,
      approval_id: id,
      agent_id: item.agent_id,
      notes: opts.reason,
    });

    if (decision === "approved") {
      // Simulate execution a moment later
      setTimeout(() => {
        item.status = "executed";
        this.appendAudit({
          action: "approval.executed",
          approval_id: id,
          agent_id: item.agent_id,
          notes: `${item.proposed_action.api_call?.method ?? "POST"} ${
            item.proposed_action.api_call?.path ?? item.proposed_action.target_system ?? "n/a"
          } → 201`,
        });
        this.emit();
      }, 600);
    }
    this.emit();
    return item;
  }

  private appendAudit(entry: {
    action: string;
    approval_id?: string;
    agent_id?: string;
    notes?: string;
  }) {
    const seq = this.audit.length + 1;
    const prev = this.audit[this.audit.length - 1];
    const payload_hash = randomHex(64);
    const hash = randomHex(64);
    this.audit.push({
      seq,
      ts: new Date().toISOString(),
      actor: this.session ? `user:${this.session.user_id}` : "system",
      action: entry.action,
      approval_id: entry.approval_id,
      agent_id: entry.agent_id,
      payload_hash,
      prev_hash: prev?.hash ?? null,
      hash,
      notes: entry.notes,
    });
    this.chain = {
      ok: true,
      total: this.audit.length,
      verified: this.audit.length,
      broken_at: null,
      checked_at: new Date().toISOString(),
    };
  }

  listAudit(): AuditEntry[] {
    return [...this.audit].reverse();
  }
  verifyChain(): ChainVerification {
    return { ...this.chain, checked_at: new Date().toISOString() };
  }

  listAgents(): Agent[] {
    return this.agents;
  }
  setTrustTier(agent_id: string, tier: Agent["trust_tier"]) {
    const a = this.agents.find((x) => x.agent_id === agent_id);
    if (!a) throw new Error("agent not found");
    a.trust_tier = tier;
    this.appendAudit({
      action: "agent.trust_tier_changed",
      agent_id,
      notes: `→ ${tier}`,
    });
    this.emit();
    return a;
  }

  getHealth(): Health {
    const counts = {
      "tier-0-mandatory": 0,
      "tier-1-spotcheck": 0,
      "tier-2-auto": 0,
    } as Record<ApprovalStatus | string, number>;
    for (const a of this.approvals) {
      if (a.status === "pending") counts[a.lane] = (counts[a.lane] || 0) + 1;
    }
    return {
      ...this.health,
      queue_depth: {
        "tier-0-mandatory": counts["tier-0-mandatory"] || 0,
        "tier-1-spotcheck": counts["tier-1-spotcheck"] || 0,
        "tier-2-auto": counts["tier-2-auto"] || 0,
      },
      audit_chain: this.verifyChain(),
      checked_at: new Date().toISOString(),
    };
  }
}

function randomHex(n: number) {
  const chars = "0123456789abcdef";
  let s = "";
  for (let i = 0; i < n; i++) s += chars[Math.floor(Math.random() * 16)];
  return s;
}

// Hot-module-safe singleton
declare global {
  // eslint-disable-next-line no-var
  var __quillMockStore: MockStore | undefined;
}
export const mockStore: MockStore = globalThis.__quillMockStore ?? new MockStore();
if (!globalThis.__quillMockStore) globalThis.__quillMockStore = mockStore;
