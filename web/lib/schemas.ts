import { z } from "zod";

// ─── Approval Queue Item ──────────────────────────────────────────────────────
// Mirrors agentic-pmo-prompts/schemas/approval_queue_item.schema.json plus the
// fields the API layer adds (status, audit, decisions).

export const LaneSchema = z.enum(["tier-0-mandatory", "tier-1-spotcheck", "tier-2-auto"]);
export type Lane = z.infer<typeof LaneSchema>;

export const ApprovalStatusSchema = z.enum([
  "pending",
  "approved",
  "rejected",
  "escalated",
  "executed",
  "expired",
]);
export type ApprovalStatus = z.infer<typeof ApprovalStatusSchema>;

export const SourceSchema = z.object({
  kind: z.string(),
  ref: z.string(),
  excerpt: z.string().optional(),
  url: z.string().url().optional().nullable(),
});

export const ProposedActionSchema = z.object({
  kind: z.string(),
  payload: z.record(z.any()),
  target_system: z.string().nullable().optional(),
  api_call: z
    .object({
      method: z.string(),
      path: z.string(),
      body_preview: z.record(z.any()).optional(),
    })
    .optional(),
});

export const ApprovalItemSchema = z.object({
  approval_id: z.string(),
  agent_id: z.string(),
  agent_version: z.string(),
  agent_model: z.string().optional(),
  prompt_version: z.string().optional(),
  workflow: z.string(),
  lane: LaneSchema,
  proposed_action: ProposedActionSchema,
  context: z.object({
    project_id: z.string(),
    sources: z.array(SourceSchema),
  }),
  confidence: z.number().min(0).max(1),
  rationale: z.string().optional(),
  escalations: z.array(z.string()).optional(),
  priority: z.enum(["low", "normal", "high", "critical"]).optional(),
  summary: z.string().optional(),
  status: ApprovalStatusSchema,
  created_at: z.string(),
  expires_at: z.string().nullable().optional(),
  decided_at: z.string().nullable().optional(),
  decided_by: z.string().nullable().optional(),
  decision_reason: z.string().nullable().optional(),
});
export type ApprovalItem = z.infer<typeof ApprovalItemSchema>;

// ─── Audit Log ────────────────────────────────────────────────────────────────

export const AuditEntrySchema = z.object({
  seq: z.number().int(),
  ts: z.string(),
  actor: z.string(),
  action: z.string(),
  approval_id: z.string().optional(),
  agent_id: z.string().optional(),
  payload_hash: z.string(),
  prev_hash: z.string().nullable(),
  hash: z.string(),
  notes: z.string().optional(),
});
export type AuditEntry = z.infer<typeof AuditEntrySchema>;

export const ChainVerificationSchema = z.object({
  ok: z.boolean(),
  total: z.number().int(),
  verified: z.number().int(),
  broken_at: z.number().int().nullable(),
  checked_at: z.string(),
});
export type ChainVerification = z.infer<typeof ChainVerificationSchema>;

// ─── Agent Fleet ──────────────────────────────────────────────────────────────

export const TrustTierSchema = z.enum(["tier-0", "tier-1", "tier-2"]);
export const AgentSchema = z.object({
  agent_id: z.string(),
  version: z.string(),
  trust_tier: TrustTierSchema,
  monthly_budget_usd: z.number(),
  spend_mtd_usd: z.number(),
  error_rate: z.number().min(0).max(1),
  approval_no_edit_rate: z.number().min(0).max(1),
  total_proposals_30d: z.number().int(),
  last_active_at: z.string().nullable(),
});
export type Agent = z.infer<typeof AgentSchema>;

// ─── Health ───────────────────────────────────────────────────────────────────

export const HealthSchema = z.object({
  queue_depth: z.object({
    "tier-0-mandatory": z.number().int(),
    "tier-1-spotcheck": z.number().int(),
    "tier-2-auto": z.number().int(),
  }),
  errors_24h: z.number().int(),
  agents_available: z.number().int(),
  agents_total: z.number().int(),
  routing: z.object({
    anthropic: z.enum(["ok", "degraded", "down", "n/a"]),
    on_prem: z.enum(["ok", "degraded", "down", "n/a"]),
  }),
  spend: z.object({
    yesterday_usd: z.number(),
    monthly_budget_usd: z.number(),
    mtd_usd: z.number(),
  }),
  audit_chain: ChainVerificationSchema,
  checked_at: z.string(),
});
export type Health = z.infer<typeof HealthSchema>;

// ─── Auth ─────────────────────────────────────────────────────────────────────

export const SessionSchema = z.object({
  user_id: z.string(),
  email: z.string(),
  display_name: z.string(),
  role: z.enum(["approver", "dual_approver", "viewer", "admin"]),
  expires_at: z.string(),
});
export type Session = z.infer<typeof SessionSchema>;
