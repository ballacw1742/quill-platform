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

// Phase F.1: chained agent run output, surfaced inside
// proposed_action.payload.chain_outputs. Optional because not every
// queue item is the result of a chain.
export const ChainStepOutputSchema = z
  .object({
    agent_id: z.string(),
    agent_version: z.string().optional(),
    ok: z.boolean(),
    confidence: z.number().nullable().optional(),
    output: z.record(z.any()).nullable().optional(),
    model: z.string().optional(),
    latency_ms: z.number().optional(),
    tokens_used: z.record(z.any()).optional(),
    error: z.string().nullable().optional(),
  })
  .passthrough();
export type ChainStepOutput = z.infer<typeof ChainStepOutputSchema>;

export const ChainOutputsSchema = z
  .object({
    chain_id: z.string(),
    steps: z.array(ChainStepOutputSchema),
    skipped: z.array(z.string()).optional(),
    errors: z.array(z.string()).optional(),
  })
  .passthrough();
export type ChainOutputs = z.infer<typeof ChainOutputsSchema>;

export const ProposedActionSchema = z.object({
  kind: z.string(),
  // payload is a free-form bag; chain_outputs (when present) is structured
  // and rendered specially by ApprovalDetailSheet.
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

/** Helper: pull chain_outputs out of a payload safely. */
export function getChainOutputs(
  payload: Record<string, unknown> | undefined,
): ChainOutputs | null {
  if (!payload) return null;
  const raw = (payload as { chain_outputs?: unknown }).chain_outputs;
  if (!raw || typeof raw !== "object") return null;
  const parsed = ChainOutputsSchema.safeParse(raw);
  return parsed.success ? parsed.data : null;
}

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

// API returns: { id, event_type, actor, approval_item_id, payload, timestamp, hash, prev_hash }
// UI used a different shape; map both via .passthrough() + transform.
export const AuditEntrySchema = z
  .object({
    // API fields
    id: z.number().int().optional(),
    event_type: z.string().optional(),
    actor: z.string(),
    approval_item_id: z.string().nullable().optional(),
    payload: z.record(z.any()).nullable().optional(),
    timestamp: z.string().optional(),
    hash: z.string().optional(),
    prev_hash: z.string().nullable().optional(),
    // UI legacy fields (kept optional so existing components still type-check)
    seq: z.number().int().optional(),
    ts: z.string().optional(),
    action: z.string().optional(),
    approval_id: z.string().optional(),
    agent_id: z.string().optional(),
    payload_hash: z.string().optional(),
    notes: z.string().optional(),
  })
  .passthrough()
  .transform((e) => ({
    ...e,
    seq: e.seq ?? e.id ?? 0,
    ts: e.ts ?? e.timestamp ?? "",
    action: e.action ?? e.event_type ?? "",
    approval_id: e.approval_id ?? e.approval_item_id ?? undefined,
    agent_id: e.agent_id ?? e.payload?.agent_id,
    payload_hash: e.payload_hash ?? e.hash ?? "",
    hash: e.hash ?? "",
    prev_hash: e.prev_hash ?? null,
  }));
export type AuditEntry = z.infer<typeof AuditEntrySchema>;

// API verify returns: { ok, chain_length, last_hash, failures }
export const ChainVerificationSchema = z
  .object({
    ok: z.boolean(),
    chain_length: z.number().int().optional(),
    last_hash: z.string().nullable().optional(),
    failures: z.array(z.any()).optional(),
    // legacy fields
    total: z.number().int().optional(),
    verified: z.number().int().optional(),
    broken_at: z.number().int().nullable().optional(),
    checked_at: z.string().optional(),
  })
  .passthrough()
  .transform((v) => ({
    ...v,
    total: v.total ?? v.chain_length ?? 0,
    verified: v.verified ?? v.chain_length ?? 0,
    broken_at: v.broken_at ?? null,
    checked_at: v.checked_at ?? new Date().toISOString(),
  }));
export type ChainVerification = z.infer<typeof ChainVerificationSchema>;

// ─── Agent Fleet ──────────────────────────────────────────────────────────────

export const TrustTierSchema = z.enum(["tier-0", "tier-1", "tier-2"]);
// API agent: { agent_id, version, trust_tier, default_lane, monthly_token_budget, enabled, notes }
// UI added more fields originally; keep them optional via passthrough.
export const AgentSchema = z
  .object({
    agent_id: z.string(),
    version: z.string(),
    trust_tier: z.string(), // tier-0-mandatory etc.
    default_lane: z.number().int().optional(),
    monthly_token_budget: z.number().optional(),
    enabled: z.boolean().optional(),
    notes: z.string().nullable().optional(),
    // Sprint DC.4 — Agent Registry fields
    display_name: z.string().optional(),
    description: z.string().nullable().optional(),
    role_summary: z.string().nullable().optional(),
    handled_intents: z.string().nullable().optional(), // JSON array as text
    framework: z.string().optional(),
    endpoint_url: z.string().nullable().optional(),
    requests_total: z.number().int().optional(),
    requests_success: z.number().int().optional(),
    requests_failed: z.number().int().optional(),
    last_invoked_at: z.string().nullable().optional(),
    created_at: z.string().nullable().optional(),
    updated_at: z.string().nullable().optional(),
    // legacy UI fields
    monthly_budget_usd: z.number().optional(),
    spend_mtd_usd: z.number().optional(),
    error_rate: z.number().optional(),
    approval_no_edit_rate: z.number().optional(),
    total_proposals_30d: z.number().int().optional(),
    last_active_at: z.string().nullable().optional(),
  })
  .passthrough()
  .transform((a) => ({
    ...a,
    monthly_budget_usd: a.monthly_budget_usd ?? 0,
    spend_mtd_usd: a.spend_mtd_usd ?? 0,
    error_rate: a.error_rate ?? 0,
    approval_no_edit_rate: a.approval_no_edit_rate ?? 0,
    total_proposals_30d: a.total_proposals_30d ?? 0,
    last_active_at: a.last_active_at ?? null,
    // Sprint DC.4 registry defaults
    display_name: a.display_name ?? "",
    framework: a.framework ?? "adk",
    requests_total: a.requests_total ?? 0,
    requests_success: a.requests_success ?? 0,
    requests_failed: a.requests_failed ?? 0,
  }));
export type Agent = z.infer<typeof AgentSchema>;

// ─── Health ───────────────────────────────────────────────────────────────────

// API /admin/health returns: { ok, db, queue_depth_pending, queue_depth_executed, audit_chain, audit_chain_length, sla_breaches_open, version }
// UI expected a richer object; we coerce.
export const HealthSchema = z
  .object({
    ok: z.boolean().optional(),
    db: z.string().optional(),
    queue_depth_pending: z.number().int().optional(),
    queue_depth_executed: z.number().int().optional(),
    audit_chain: z.union([z.string(), ChainVerificationSchema]).optional(),
    audit_chain_length: z.number().int().optional(),
    sla_breaches_open: z.number().int().optional(),
    version: z.string().optional(),
    // legacy UI fields
    queue_depth: z.any().optional(),
    errors_24h: z.number().int().optional(),
    agents_available: z.number().int().optional(),
    agents_total: z.number().int().optional(),
    routing: z.any().optional(),
    spend: z.any().optional(),
    checked_at: z.string().optional(),
  })
  .passthrough()
  .transform((h) => ({
    ...h,
    queue_depth: h.queue_depth ?? {
      "tier-0-mandatory": 0,
      "tier-1-spotcheck": h.queue_depth_pending ?? 0,
      "tier-2-auto": 0,
    },
    errors_24h: h.errors_24h ?? 0,
    agents_available: h.agents_available ?? 0,
    agents_total: h.agents_total ?? 0,
    routing: h.routing ?? { anthropic: "ok", on_prem: "n/a" },
    spend: h.spend ?? {
      yesterday_usd: 0,
      monthly_budget_usd: 1000,
      mtd_usd: 0,
    },
    audit_chain: typeof h.audit_chain === "string"
      ? {
          ok: h.audit_chain === "ok",
          total: h.audit_chain_length ?? 0,
          verified: h.audit_chain_length ?? 0,
          broken_at: null,
          checked_at: new Date().toISOString(),
        }
      : (h.audit_chain ?? {
          ok: true,
          total: 0,
          verified: 0,
          broken_at: null,
          checked_at: new Date().toISOString(),
        }),
    checked_at: h.checked_at ?? new Date().toISOString(),
  }));
export type Health = z.infer<typeof HealthSchema>;

// ─── Auth ─────────────────────────────────────────────────────────────────────

// API login response: { access_token, token_type, user_id, role }
// API /auth/me response: { id, email, display_name, role, telegram_chat_id, created_at }
// We accept both shapes here; UI surfaces what it has.
export const RoleSchema = z
  .enum(["owner", "partner", "approver", "dual_approver", "viewer", "admin"])
  .or(z.string());

// Permissive: accepts both /login and /auth/me shapes. user_id is normalized
// from `id` if `user_id` isn't present (via the transform).
export const SessionSchema = z
  .object({
    // Either user_id (from /login) or id (from /auth/me).
    user_id: z.string().optional(),
    id: z.string().optional(),
    email: z.string().optional(),
    display_name: z.string().optional(),
    role: RoleSchema.optional(),
    expires_at: z.string().optional(),
    access_token: z.string().optional(),
    token_type: z.string().optional(),
    telegram_chat_id: z.string().nullable().optional(),
    created_at: z.string().optional(),
  })
  .passthrough()
  .transform((s) => ({
    ...s,
    user_id: s.user_id ?? s.id ?? "",
  }));
export type Session = z.infer<typeof SessionSchema>;

export const MeSchema = SessionSchema;
export type Me = Session;

// ─── Documents (Phase D) ──────────────────────────────────────────────────────
//
// Mirrors web/DOCUMENTS_SPEC.md §"Document schema" / §"API surface".
// The API returns ISO timestamp strings; we keep them as strings here and let
// the UI render them via date-fns. `tags` always defaults to `[]`. `summary`
// and `body_markdown` are required on full reads but the list endpoint omits
// the body — we reuse the same nullable shape via DocumentSummarySchema.

export const ArtifactTypeSchema = z.enum([
  "status_update",
  "coordinator_artifact",
  "pm_analysis",
  "comms_draft",
  "knowledge_entry",
]);
export type ArtifactType = z.infer<typeof ArtifactTypeSchema>;

/**
 * Permissive artifact type — accepts the canonical values above plus any
 * unknown string the server might add later. We render unknown types with a
 * default icon + pretty-cased label.
 */
export const ArtifactTypeLooseSchema = z.union([ArtifactTypeSchema, z.string()]);
export type ArtifactTypeLoose = z.infer<typeof ArtifactTypeLooseSchema>;

export const DocumentExportFormatSchema = z.enum(["md", "pdf", "docx"]);
export type DocumentExportFormat = z.infer<typeof DocumentExportFormatSchema>;

/**
 * Lightweight document shape returned by `/v1/documents` (list endpoint).
 * Drops `body_markdown` to keep payloads compact.
 */
export const DocumentSummarySchema = z
  .object({
    id: z.string(),
    artifact_id: z.string(),
    artifact_type: ArtifactTypeLooseSchema,
    title: z.string(),
    summary: z.string().default(""),
    agent_id: z.string(),
    agent_display_name: z.string().default(""),
    created_at: z.string(),
    approved_at: z.string().nullable().optional(),
    tags: z.array(z.string()).optional().default([]),
    drive_url: z.string().nullable().optional(),
    // Some metadata may be carried for typing process docs (SOP / RACI / etc.)
    metadata: z.record(z.string(), z.unknown()).nullable().optional(),
  })
  .passthrough();
export type DocumentSummary = z.infer<typeof DocumentSummarySchema>;

/**
 * Full document shape returned by `/v1/documents/{id}`. Adds the markdown
 * body, approver info, and the internal blob path.
 */
export const DocumentSchema = z
  .object({
    id: z.string(),
    artifact_id: z.string(),
    artifact_type: ArtifactTypeLooseSchema,
    title: z.string(),
    summary: z.string().default(""),
    body_markdown: z.string().default(""),
    agent_id: z.string(),
    agent_display_name: z.string().default(""),
    created_at: z.string(),
    approved_at: z.string().nullable().optional(),
    approved_by: z.string().nullable().optional(),
    approval_id: z.string().nullable().optional(),
    tags: z.array(z.string()).optional().default([]),
    drive_url: z.string().nullable().optional(),
    minio_path: z.string().nullable().optional(),
    // Full artifact payload (Sprint G.7). Nullable because existing docs
    // pre-dating this sprint have NULL metadata until backfilled.
    metadata: z.record(z.string(), z.unknown()).nullable().optional(),
  })
  .passthrough();
export type Document = z.infer<typeof DocumentSchema>;

/** List envelope returned by `/v1/documents`. */
export const DocumentListPageSchema = z.object({
  items: z.array(DocumentSummarySchema),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
});
export type DocumentListPage = z.infer<typeof DocumentListPageSchema>;

/** Search hit shape returned by `/v1/documents/search`. */
export const DocumentSearchHitSchema = DocumentSummarySchema.extend({
  score: z.number().optional(),
  snippet: z.string().optional(),
});
export type DocumentSearchHit = z.infer<typeof DocumentSearchHitSchema>;

export const DocumentSearchResultSchema = z.object({
  items: z.array(DocumentSearchHitSchema),
  total: z.number().int(),
  q: z.string(),
});
export type DocumentSearchResult = z.infer<typeof DocumentSearchResultSchema>;

export const DocumentDriveLinkSchema = z.object({
  url: z.string().nullable(),
  status: z.string().optional(),
});
export type DocumentDriveLink = z.infer<typeof DocumentDriveLinkSchema>;

// ─── Estimates / AACE classification (Phase G.2) ─────────────────────────────
//
// Mirrors:
//   agentic-pmo-prompts/schemas/aace_classification.schema.json
//   agentic-pmo-prompts/schemas/cost_schedule_package.schema.json
//   api/app/routes/estimates.py UploadOut / StatusOut / StartEstimationOut
//
// All zod shapes use `.passthrough()` because:
//   1. The agent schemas allow forward-compatible fields downstream of agent
//      versioning, and we don't want a strict parse to crash the UI.
//   2. The API stubs may add fields (audit hashes, ids, etc.) without notice.
// We transform/normalise only the fields the UI consumes directly.

export const EstimateUploadFileEntrySchema = z
  .object({
    filename: z.string(),
    kind: z.string(), // "pdf" | "ifc" | "dxf" | "dwg" | "rvt" | "other"
    size_bytes: z.number().int().min(0).default(0),
    extraction_status: z.string().default("pending"), // "ok" | "partial" | "failed" | "pending"
    extraction_summary: z.string().default(""),
    minio_key: z.string().nullable().optional(),
  })
  .passthrough();
export type EstimateUploadFileEntry = z.infer<typeof EstimateUploadFileEntrySchema>;

/** GET /v1/estimates/{upload_id}/status — top-level status envelope. */
export const EstimateStatusEnumSchema = z.union([
  z.enum([
    "queued",
    "extracting",
    "classifying",
    "awaiting_classification_approval",
    "estimating",
    "awaiting_package_approval",
    "done",
    "failed",
  ]),
  z.string(),
]);
export type EstimateStatusEnum = z.infer<typeof EstimateStatusEnumSchema>;

export const EstimateStatusSchema = z
  .object({
    upload_id: z.string(),
    status: EstimateStatusEnumSchema,
    project_label: z.string().default(""),
    notes: z.string().default(""),
    uploaded_files: z.array(EstimateUploadFileEntrySchema).default([]),
    classification_artifact_id: z.string().nullable().optional(),
    package_artifact_id: z.string().nullable().optional(),
    created_at: z.string().optional(),
    updated_at: z.string().optional(),
    error_message: z.string().nullable().optional(),
    // Forward-compat: the API may eventually surface the full classification
    // and package artifacts inline so the UI doesn't need a second hop.
    classification: z.unknown().nullable().optional(),
    package: z.unknown().nullable().optional(),
  })
  .passthrough();
export type EstimateStatus = z.infer<typeof EstimateStatusSchema>;

/** POST /v1/estimates/upload response. */
export const EstimateUploadResponseSchema = z
  .object({
    upload_id: z.string(),
    file_count: z.number().int().min(0).default(0),
    total_bytes: z.number().int().min(0).default(0),
    extraction_started: z.boolean().default(true),
  })
  .passthrough();
export type EstimateUploadResponse = z.infer<typeof EstimateUploadResponseSchema>;

/** POST /v1/estimates/{upload_id}/start_estimation response. */
export const StartEstimationResponseSchema = z
  .object({
    ok: z.boolean().default(true),
    upload_id: z.string(),
    audit_hash: z.string().optional(),
    agent_id: z.string().optional(),
  })
  .passthrough();
export type StartEstimationResponse = z.infer<typeof StartEstimationResponseSchema>;

// ── AACE classification artifact metadata ────────────────────────────────────

export const AaceClassEnumSchema = z.union([z.enum(["5", "4", "3", "2"]), z.string()]);
export type AaceClassEnum = z.infer<typeof AaceClassEnumSchema>;

export const AaceEvidenceItemSchema = z
  .object({
    category: z.string(),
    score: z.number().min(0).max(1).default(0),
    evidence: z.string().default(""),
  })
  .passthrough();
export type AaceEvidenceItem = z.infer<typeof AaceEvidenceItemSchema>;

export const AaceMissingItemSchema = z
  .object({
    deliverable: z.string(),
    rationale: z.string().default(""),
    would_unlock_class: AaceClassEnumSchema,
  })
  .passthrough();
export type AaceMissingItem = z.infer<typeof AaceMissingItemSchema>;

export const AaceClassificationMetadataSchema = z
  .object({
    project_label: z.string().default(""),
    class: AaceClassEnumSchema,
    design_maturity_estimate_pct: z.number().min(0).max(100).default(0),
    accuracy_range: z
      .object({
        low_pct: z.number(),
        high_pct: z.number(),
      })
      .partial()
      .passthrough()
      .optional(),
    supporting_evidence: z.array(AaceEvidenceItemSchema).default([]),
    missing_for_next_class: z.array(AaceMissingItemSchema).default([]),
    uploaded_files: z.array(EstimateUploadFileEntrySchema).default([]),
    design_disciplines_detected: z.array(z.string()).optional(),
    upload_id: z.string().optional(), // convenience surfaced by API for re-link
  })
  .passthrough();
export type AaceClassificationMetadata = z.infer<typeof AaceClassificationMetadataSchema>;

/** Full aace_classification document/artifact (extends pm_artifact_base). */
export const AaceClassificationSchema = z
  .object({
    artifact_type: z.literal("aace_classification").or(z.string()),
    artifact_id: z.string().optional(),
    title: z.string().default(""),
    summary: z.string().default(""),
    body_markdown: z.string().default(""),
    metadata: AaceClassificationMetadataSchema,
    citations: z.array(z.unknown()).optional(),
    confidence: z.number().min(0).max(1).default(0),
    escalation_reasons: z.array(z.string()).optional(),
  })
  .passthrough();
export type AaceClassification = z.infer<typeof AaceClassificationSchema>;

// ── Cost & Schedule Package artifact metadata ────────────────────────────────

export const CostUnitSchema = z.union([
  z.enum([
    "EA", "SF", "CY", "LB", "LF", "LS", "HR", "CF", "TON", "MWHr", "MW", "GAL", "KIP",
  ]),
  z.string(),
]);

export const EstimateRowSchema = z
  .object({
    csi_section: z.string(),
    description: z.string().default(""),
    quantity: z.number().min(0).default(0),
    unit: CostUnitSchema,
    unit_rate_usd: z.number().min(0).default(0),
    extended_usd: z.number().min(0).default(0),
    rate_source: z.string().default("library_v0_1"),
    confidence: z.number().min(0).max(1).default(0),
    notes: z.string().optional(),
    source_citation: z.string().optional(),
  })
  .passthrough();
export type EstimateRow = z.infer<typeof EstimateRowSchema>;

export const IndirectItemSchema = z
  .object({
    label: z.string(),
    pct_of_direct: z.number().nullable().optional(),
    amount_usd: z.number().min(0).default(0),
    notes: z.string().optional(),
  })
  .passthrough();
export type IndirectItem = z.infer<typeof IndirectItemSchema>;

export const ContingencySchema = z
  .object({
    pct_of_direct_plus_indirect: z.number().min(0).max(100).default(0),
    amount_usd: z.number().min(0).default(0),
    rationale: z.string().default(""),
  })
  .passthrough();
export type Contingency = z.infer<typeof ContingencySchema>;

export const EscalationSchema = z
  .object({
    annual_pct: z.number(),
    midpoint_year: z.string(),
    amount_usd: z.number(),
  })
  .passthrough();
export type Escalation = z.infer<typeof EscalationSchema>;

export const EstimateBlockSchema = z
  .object({
    rows: z.array(EstimateRowSchema).default([]),
    subtotal_direct_usd: z.number().min(0).default(0),
    indirects: z.array(IndirectItemSchema).default([]),
    contingency: ContingencySchema.optional(),
    escalation: EscalationSchema.optional(),
    total_usd: z.number().min(0).default(0),
    total_per_sf_usd: z.number().nullable().optional(),
    total_per_mw_usd: z.number().nullable().optional(),
  })
  .passthrough();
export type EstimateBlock = z.infer<typeof EstimateBlockSchema>;

export const PredecessorSchema = z
  .object({
    id: z.string(),
    type: z.union([z.enum(["FS", "SS", "FF", "SF"]), z.string()]).default("FS"),
    lag_days: z.number().int().optional(),
  })
  .passthrough();
export type Predecessor = z.infer<typeof PredecessorSchema>;

export const ScheduleResourceSchema = z
  .object({
    type: z.string(),
    quantity: z.number().min(0).default(0),
    unit: z.string().optional(),
  })
  .passthrough();
export type ScheduleResource = z.infer<typeof ScheduleResourceSchema>;

export const ScheduleActivitySchema = z
  .object({
    id: z.string(),
    name: z.string().default(""),
    wbs: z.string().optional(),
    duration_days: z.number().int().min(0).default(0),
    predecessors: z.array(PredecessorSchema).optional(),
    resources: z.array(ScheduleResourceSchema).optional(),
    milestone: z.boolean().optional(),
    critical_path: z.boolean().optional(),
    notes: z.string().optional(),
    // Optional convenience fields some agents may emit so the UI doesn't have
    // to topologically resolve a network just to render a Gantt.
    start_date: z.string().optional(),
    end_date: z.string().optional(),
  })
  .passthrough();
export type ScheduleActivity = z.infer<typeof ScheduleActivitySchema>;

export const ScheduleMilestoneSchema = z
  .object({
    id: z.string(),
    name: z.string(),
    target_date: z.string().nullable().optional(),
    achieved_at: z.string().nullable().optional(),
    notes: z.string().optional(),
  })
  .passthrough();
export type ScheduleMilestone = z.infer<typeof ScheduleMilestoneSchema>;

export const ScheduleBlockSchema = z
  .object({
    level: z.number().int().min(1).max(5).default(1),
    activities: z.array(ScheduleActivitySchema).default([]),
    milestones: z.array(ScheduleMilestoneSchema).optional(),
    total_duration_days: z.number().int().min(0).default(0),
    critical_path_ids: z.array(z.string()).optional(),
    calendar_assumptions: z.string().optional(),
  })
  .passthrough();
export type ScheduleBlock = z.infer<typeof ScheduleBlockSchema>;

export const RiskItemSchema = z
  .object({
    id: z.string(),
    description: z.string().default(""),
    category: z.string().default("scope"),
    likelihood: z.union([z.enum(["low", "medium", "high"]), z.string()]).default("low"),
    impact_usd_low: z.number().nullable().optional(),
    impact_usd_high: z.number().nullable().optional(),
    schedule_impact_days_low: z.number().nullable().optional(),
    schedule_impact_days_high: z.number().nullable().optional(),
    mitigation: z.string().optional(),
    owner_role: z.string().optional(),
  })
  .passthrough();
export type RiskItem = z.infer<typeof RiskItemSchema>;

export const PackageMissingItemSchema = z
  .object({
    deliverable: z.string(),
    rationale: z.string().default(""),
    would_unlock_class: AaceClassEnumSchema,
    estimated_cost_to_complete_usd: z.number().nullable().optional(),
  })
  .passthrough();
export type PackageMissingItem = z.infer<typeof PackageMissingItemSchema>;

export const HeadlineMetricsSchema = z
  .object({
    total_usd: z.number().nullable().optional(),
    total_per_sf_usd: z.number().nullable().optional(),
    total_per_mw_usd: z.number().nullable().optional(),
    total_duration_days: z.number().nullable().optional(),
    critical_path_count: z.number().nullable().optional(),
  })
  .passthrough();
export type HeadlineMetrics = z.infer<typeof HeadlineMetricsSchema>;

export const CostSchedulePackageMetadataSchema = z
  .object({
    project_label: z.string().default(""),
    aace_class: AaceClassEnumSchema,
    // schedule_level may be either an integer (1..5) or a string like
    // "Level 1" / "L1" depending on the agent run. Normalize to an int 1..5.
    schedule_level: z
      .union([z.number(), z.string()])
      .transform((v) => {
        if (typeof v === "number") return v;
        const m = String(v).match(/(\d+)/);
        return m ? parseInt(m[1], 10) : 1;
      })
      .pipe(z.number().int().min(1).max(5))
      .default(1),
    currency: z.string().default("USD"),
    base_year: z.string().default("2026"),
    estimate: EstimateBlockSchema,
    schedule: ScheduleBlockSchema,
    basis_of_estimate: z.string().default(""),
    basis_of_schedule: z.string().default(""),
    risk_register: z.array(RiskItemSchema).default([]),
    missing_info_to_next_class: z.array(PackageMissingItemSchema).default([]),
    uploaded_files: z.array(EstimateUploadFileEntrySchema).default([]),
    library_version: z.string().default(""),
    headline_metrics: HeadlineMetricsSchema.optional(),
    upload_id: z.string().optional(),
  })
  .passthrough();
export type CostSchedulePackageMetadata = z.infer<typeof CostSchedulePackageMetadataSchema>;

export const CostSchedulePackageSchema = z
  .object({
    artifact_type: z.literal("cost_schedule_package").or(z.string()),
    artifact_id: z.string().optional(),
    title: z.string().default(""),
    summary: z.string().default(""),
    body_markdown: z.string().default(""),
    metadata: CostSchedulePackageMetadataSchema,
    citations: z.array(z.unknown()).optional(),
    confidence: z.number().min(0).max(1).default(0),
    escalation_reasons: z.array(z.string()).optional(),
  })
  .passthrough();
export type CostSchedulePackage = z.infer<typeof CostSchedulePackageSchema>;

export const EstimateExportFormatSchema = z.enum(["md", "csv", "xer", "pdf"]);
export type EstimateExportFormat = z.infer<typeof EstimateExportFormatSchema>;

/** Listing row returned by GET /v1/estimates (server-canonical shape). */
export const EstimateListItemSchema = z
  .object({
    upload_id: z.string(),
    project_label: z.string().default(""),
    notes: z.string().default(""),
    status: EstimateStatusEnumSchema,
    created_at: z.string(),
    updated_at: z.string(),
    classification_artifact_id: z.string().nullable().optional(),
    package_artifact_id: z.string().nullable().optional(),
    error_message: z.string().nullable().optional(),
  })
  .passthrough();
export type EstimateListItem = z.infer<typeof EstimateListItemSchema>;

export const EstimateListResponseSchema = z
  .object({
    items: z.array(EstimateListItemSchema).default([]),
    total: z.number().int().min(0).default(0),
    limit: z.number().int().min(0).default(50),
    offset: z.number().int().min(0).default(0),
  })
  .passthrough();
export type EstimateListResponse = z.infer<typeof EstimateListResponseSchema>;

/** True while the upload is still progressing through the pipeline. */
export function isEstimateInFlight(status: string | undefined): boolean {
  if (!status) return false;
  return [
    "queued",
    "extracting",
    "classifying",
    "awaiting_classification_approval",
    "estimating",
    "awaiting_package_approval",
  ].includes(status);
}


// ─── Dev Chat (Sprint DC.1) ──────────────────────────────────────────────────

export const DevChatMessageSchema = z.object({
  id: z.string(),
  thread_id: z.string(),
  role: z.enum(["user", "agent", "system"]),
  content: z.string(),
  metadata: z.record(z.any()).nullable().optional(),
  status: z.enum(["queued", "streaming", "completed", "failed", "cancelled"]),
  commit_sha: z.string().nullable().optional(),
  files_changed: z.array(z.string()).nullable().optional(),
  cost_usd: z.number().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
  completed_at: z.string().nullable().optional(),
});
export type DevChatMessage = z.infer<typeof DevChatMessageSchema>;

export const DevChatThreadSchema = z.object({
  id: z.string(),
  user_id: z.string(),
  state: z.enum(["idle", "in_progress"]),
  created_at: z.string(),
  updated_at: z.string(),
});
export type DevChatThread = z.infer<typeof DevChatThreadSchema>;

export const DevChatThreadPageSchema = z.object({
  thread: DevChatThreadSchema,
  messages: z.array(DevChatMessageSchema),
  total: z.number().int(),
  limit: z.number().int(),
});
export type DevChatThreadPage = z.infer<typeof DevChatThreadPageSchema>;

export const DevChatStatusSchema = z.object({
  state: z.enum(["idle", "in_progress"]),
  current_task_id: z.string().nullable().optional(),
  current_message_id: z.string().nullable().optional(),
  started_at: z.string().nullable().optional(),
});
export type DevChatStatus = z.infer<typeof DevChatStatusSchema>;

export const DevChatSendResponseSchema = z.object({
  task_id: z.string(),
  message_id: z.string(),
  thread_state: z.string(),
});
export type DevChatSendResponse = z.infer<typeof DevChatSendResponseSchema>;

// ─── Contracts (Sprint Contracts.1) ──────────────────────────────────────────

export const CONTRACT_DISCLAIMER =
  "AI-generated analysis. This is not legal advice. Review with qualified counsel before relying on it for any binding decision.";

export const ContractTypeSchema = z.union([
  z.enum([
    "owner_gc",
    "subcontract",
    "change_order",
    "purchase_order",
    "letter_of_intent",
    "nda",
    "msa",
    "equipment_lease",
    "insurance_certificate",
    "lien_waiver",
    "other",
    "unknown",
  ]),
  z.string(),
]);
export type ContractType = z.infer<typeof ContractTypeSchema>;

export const ContractStatusEnumSchema = z.union([
  z.enum([
    "uploaded",
    "extracting",
    "extracted",
    "reviewing",
    "reviewed",
    "drafting",
    "drafted",
    "failed",
  ]),
  z.string(),
]);
export type ContractStatusEnum = z.infer<typeof ContractStatusEnumSchema>;

export const ContractUploadedFileEntrySchema = z
  .object({
    filename: z.string(),
    kind: z.string(),
    size_bytes: z.number().int().min(0).default(0),
    extraction_status: z.string().default("pending"),
    extraction_summary: z.string().default(""),
    minio_key: z.string().nullable().optional(),
  })
  .passthrough();
export type ContractUploadedFileEntry = z.infer<typeof ContractUploadedFileEntrySchema>;

/** POST /v1/contracts/upload response. */
export const ContractUploadResponseSchema = z
  .object({
    upload_id: z.string(),
    file_count: z.number().int().min(0).default(0),
    total_bytes: z.number().int().min(0).default(0),
    extraction_started: z.boolean().default(true),
  })
  .passthrough();
export type ContractUploadResponse = z.infer<typeof ContractUploadResponseSchema>;

/** GET /v1/contracts/{upload_id}/status */
export const ContractStatusSchema = z
  .object({
    upload_id: z.string(),
    status: ContractStatusEnumSchema,
    contract_type: ContractTypeSchema.nullable().optional(),
    effective_date: z.string().nullable().optional(),
    expiration_date: z.string().nullable().optional(),
    error_message: z.string().nullable().optional(),
    created_at: z.string().optional(),
    updated_at: z.string().optional(),
  })
  .passthrough();
export type ContractStatus = z.infer<typeof ContractStatusSchema>;

/** Lightweight item used in list responses. */
export const ContractListItemSchema = z
  .object({
    upload_id: z.string(),
    project_label: z.string().default(""),
    contract_type: ContractTypeSchema.nullable().optional(),
    status: ContractStatusEnumSchema,
    source: z.string().default("upload"),
    effective_date: z.string().nullable().optional(),
    expiration_date: z.string().nullable().optional(),
    total_value_usd: z.number().nullable().optional(),
    created_at: z.string().optional(),
    updated_at: z.string().optional(),
    error_message: z.string().nullable().optional(),
  })
  .passthrough();
export type ContractListItem = z.infer<typeof ContractListItemSchema>;

/** Full contract record. */
export const ContractSchema = z
  .object({
    upload_id: z.string(),
    project_label: z.string().default(""),
    contract_type: ContractTypeSchema.nullable().optional(),
    status: ContractStatusEnumSchema,
    source: z.string().default("upload"),
    uploaded_files: z.array(ContractUploadedFileEntrySchema).default([]),
    extracted_fields: z.record(z.any()).nullable().optional(),
    parties: z.array(z.record(z.any())).default([]),
    effective_date: z.string().nullable().optional(),
    expiration_date: z.string().nullable().optional(),
    total_value_usd: z.number().nullable().optional(),
    notes: z.string().default(""),
    error_message: z.string().nullable().optional(),
    classification_artifact_id: z.string().nullable().optional(),
    review_artifact_id: z.string().nullable().optional(),
    created_at: z.string().optional(),
    updated_at: z.string().optional(),
    disclaimer: z.string(),
  })
  .passthrough();
export type Contract = z.infer<typeof ContractSchema>;

/** GET /v1/contracts list page. */
export const ContractListPageSchema = z
  .object({
    items: z.array(ContractListItemSchema),
    total: z.number().int().min(0),
    limit: z.number().int().min(1),
    offset: z.number().int().min(0),
  })
  .passthrough();
export type ContractListPage = z.infer<typeof ContractListPageSchema>;

// ── Contract extraction metadata (mirrors contract_extraction.schema.json 1:1) ──

export const ContractPartySchema = z
  .object({
    role: z.string(),
    name: z.string(),
    address: z.string().nullable().optional(),
    contact: z.string().nullable().optional(),
  })
  .passthrough();
export type ContractParty = z.infer<typeof ContractPartySchema>;

export const ContractClauseEntrySchema = z
  .union([
    z.null(),
    z
      .object({
        verbatim: z.string(),
        paraphrase: z.string(),
      })
      .passthrough(),
  ]);
export type ContractClauseEntry = z.infer<typeof ContractClauseEntrySchema>;

export const ContractNotableClausesSchema = z
  .object({
    indemnification: ContractClauseEntrySchema.optional(),
    termination: ContractClauseEntrySchema.optional(),
    dispute_resolution: ContractClauseEntrySchema.optional(),
    insurance_requirements: ContractClauseEntrySchema.optional(),
    limitation_of_liability: ContractClauseEntrySchema.optional(),
    change_orders: ContractClauseEntrySchema.optional(),
    payment_terms: ContractClauseEntrySchema.optional(),
  })
  .passthrough();
export type ContractNotableClauses = z.infer<typeof ContractNotableClausesSchema>;

export const ContractExtractionMetadataSchema = z
  .object({
    artifact_type: z.literal("contract_extraction"),
    contract_type: ContractTypeSchema,
    confidence: z.number().min(0).max(1),
    parties: z.array(ContractPartySchema).default([]),
    effective_date: z.string().nullable().optional(),
    expiration_date: z.string().nullable().optional(),
    total_value_usd: z.number().nullable().optional(),
    payment_terms: z.string().nullable().optional(),
    payment_schedule: z
      .array(
        z
          .object({
            description: z.string(),
            amount_usd: z.number().nullable().optional(),
            due: z.string(),
            condition: z.string().nullable().optional(),
          })
          .passthrough(),
      )
      .default([]),
    key_milestones: z
      .array(
        z
          .object({
            description: z.string(),
            date: z.string(),
          })
          .passthrough(),
      )
      .default([]),
    obligations: z.record(z.array(z.string())).default({}),
    notable_clauses: ContractNotableClausesSchema.optional(),
    notes: z.string().default(""),
    disclaimer: z.string(),
    citations: z
      .array(
        z
          .object({
            quote: z.string(),
            location: z.string(),
          })
          .passthrough(),
      )
      .default([]),
  })
  .passthrough();
export type ContractExtractionMetadata = z.infer<typeof ContractExtractionMetadataSchema>;

// ─── Contracts Review + Interpretation (Sprint Contracts.2) ──────────────────

const CANONICAL_DISCLAIMER =
  "AI-generated analysis. This is not legal advice. Review with qualified counsel before relying on it for any binding decision." as const;

// ── Risk flag ──────────────────────────────────────────────────────────────
export const ContractRiskFlagSchema = z
  .object({
    severity: z.enum(["critical", "high", "medium", "low", "info"]),
    category: z.string(),
    title: z.string(),
    summary: z.string(),
    verbatim: z.string(),
    location: z.string(),
    why_it_matters: z.string(),
    suggested_action: z.string(),
    suggested_redline: z.string().optional(),
  })
  .passthrough();
export type ContractRiskFlag = z.infer<typeof ContractRiskFlagSchema>;

// ── Missing protection ─────────────────────────────────────────────────────
export const ContractMissingProtectionSchema = z
  .object({
    category: z.string(),
    title: z.string(),
    why_typical: z.string(),
    suggested_clause: z.string(),
  })
  .passthrough();
export type ContractMissingProtection = z.infer<typeof ContractMissingProtectionSchema>;

// ── Market terms entry ─────────────────────────────────────────────────────
export const MarketTermsEntrySchema = z
  .object({
    verdict: z.enum([
      "in-market",
      "off-market-favorable",
      "off-market-unfavorable",
      "not-present",
      "unclear",
    ]),
    notes: z.string(),
  })
  .passthrough();
export type MarketTermsEntry = z.infer<typeof MarketTermsEntrySchema>;

// ── Market terms assessment ────────────────────────────────────────────────
export const MarketTermsAssessmentSchema = z
  .object({
    payment_terms: MarketTermsEntrySchema,
    retention: MarketTermsEntrySchema,
    indemnification: MarketTermsEntrySchema,
    limitation_of_liability: MarketTermsEntrySchema,
    termination: MarketTermsEntrySchema,
    change_orders: MarketTermsEntrySchema,
    dispute_resolution: MarketTermsEntrySchema,
    insurance: MarketTermsEntrySchema,
  })
  .passthrough();
export type MarketTermsAssessment = z.infer<typeof MarketTermsAssessmentSchema>;

// ── Full contract review artifact ──────────────────────────────────────────
export const ContractReviewMetadataSchema = z
  .object({
    risk_flags: z.array(ContractRiskFlagSchema).default([]),
    missing_protections: z.array(ContractMissingProtectionSchema).default([]),
    market_terms_assessment: MarketTermsAssessmentSchema,
    plain_english_summary: z.string(),
    recommended_actions: z.array(z.string()).default([]),
    disclaimer: z.string().default(CANONICAL_DISCLAIMER),
    citations: z
      .array(
        z.object({ quote: z.string(), location: z.string() }).passthrough()
      )
      .default([]),
  })
  .passthrough();
export type ContractReviewMetadata = z.infer<typeof ContractReviewMetadataSchema>;

export const ContractReviewSchema = z
  .object({
    artifact_type: z.literal("contract_review").optional(),
    review_artifact_id: z.string().optional(),
    created_at: z.string().optional(),
    severity_counts: z
      .object({
        critical: z.number().default(0),
        high: z.number().default(0),
        medium: z.number().default(0),
        low: z.number().default(0),
        info: z.number().default(0),
      })
      .optional(),
    ...ContractReviewMetadataSchema.shape,
  })
  .passthrough();
export type ContractReview = z.infer<typeof ContractReviewSchema>;

// ── Contract review list ───────────────────────────────────────────────────
export const ContractReviewListItemSchema = z
  .object({
    review_artifact_id: z.string(),
    created_at: z.string(),
    severity_counts: z.object({
      critical: z.number().default(0),
      high: z.number().default(0),
      medium: z.number().default(0),
      low: z.number().default(0),
      info: z.number().default(0),
    }),
  })
  .passthrough();
export type ContractReviewListItem = z.infer<typeof ContractReviewListItemSchema>;

export const ContractReviewListResponseSchema = z.object({
  items: z.array(ContractReviewListItemSchema),
  total: z.number(),
});
export type ContractReviewListResponse = z.infer<typeof ContractReviewListResponseSchema>;

// ── Supporting clause ──────────────────────────────────────────────────────
export const SupportingClauseSchema = z
  .object({
    verbatim: z.string(),
    location: z.string(),
    why_relevant: z.string(),
  })
  .passthrough();
export type SupportingClause = z.infer<typeof SupportingClauseSchema>;

// ── Contract interpretation (single Q&A) ──────────────────────────────────
export const ContractInterpretationSchema = z
  .object({
    contract_upload_id: z.string(),
    interpretation_id: z.string().optional(),
    question: z.string(),
    answer: z.string(),
    supporting_clauses: z.array(SupportingClauseSchema).default([]),
    confidence: z.number().min(0).max(1),
    caveats: z
      .array(z.object({ caveat: z.string() }).passthrough())
      .default([]),
    disclaimer: z.string().default(CANONICAL_DISCLAIMER),
    created_at: z.string().optional(),
  })
  .passthrough();
export type ContractInterpretation = z.infer<typeof ContractInterpretationSchema>;

// ── Contract interpretations list ─────────────────────────────────────────
export const ContractInterpretationListResponseSchema = z.object({
  items: z.array(ContractInterpretationSchema),
  total: z.number(),
});
export type ContractInterpretationListResponse = z.infer<
  typeof ContractInterpretationListResponseSchema
>;

// ── Contracts.3 — Drafter ─────────────────────────────────────────────────

// ── Template metadata ──────────────────────────────────────────────────────
export const ContractTemplateSchema = z
  .object({
    template_id: z.string(),
    contract_type: z.string(),
    display_name: z.string(),
    version: z.string().default("0.1.0"),
    required_variables: z.array(z.string()).default([]),
    optional_variables: z.array(z.string()).default([]),
    jurisdiction_notes: z.string().default(""),
    suitable_for: z.string().default(""),
    body: z.string().default(""),
  })
  .passthrough();
export type ContractTemplate = z.infer<typeof ContractTemplateSchema>;

export const ContractTemplateListResponseSchema = z.object({
  items: z.array(ContractTemplateSchema),
  total: z.number(),
});
export type ContractTemplateListResponse = z.infer<
  typeof ContractTemplateListResponseSchema
>;

// ── Draft request ──────────────────────────────────────────────────────────
export const ContractDraftPartySchema = z
  .object({
    role: z.string(),
    name: z.string(),
    address: z.string().optional(),
    contact: z.string().optional(),
  })
  .passthrough();

export const ContractDraftKeyTermSchema = z
  .object({
    topic: z.string(),
    requirement: z.string(),
  })
  .passthrough();

export const ContractDraftRequestSchema = z.object({
  mode: z.enum(["template", "negotiated"]),
  contract_type: z.string(),
  template_id: z.string().nullable().optional(),
  parties: z.array(ContractDraftPartySchema).default([]),
  effective_date: z.string().nullable().optional(),
  expiration_date: z.string().nullable().optional(),
  total_value_usd: z.number().nullable().optional(),
  payment_terms: z.string().nullable().optional(),
  scope_summary: z.string().default(""),
  key_terms_requested: z.array(ContractDraftKeyTermSchema).default([]),
  jurisdiction: z.string().default("Ohio"),
  notes: z.string().default(""),
  prior_contract_upload_id: z.string().nullable().optional(),
});
export type ContractDraftRequest = z.infer<typeof ContractDraftRequestSchema>;

// ── Draft metadata (matches contract_draft.schema.json) ───────────────────
export const ContractDraftSectionSchema = z
  .object({
    heading: z.string(),
    anchor: z.string(),
    summary: z.string(),
  })
  .passthrough();

export const ContractDraftAttorneyFocusSchema = z
  .object({
    topic: z.string(),
    why: z.string(),
    suggested_question: z.string(),
  })
  .passthrough();

export const ContractDraftAssumptionSchema = z
  .object({
    topic: z.string(),
    assumption: z.string(),
    why_made: z.string(),
  })
  .passthrough();

export const ContractDraftMetadataSchema = z
  .object({
    artifact_type: z.literal("contract_draft").optional(),
    contract_type: z.string(),
    mode: z.enum(["template", "negotiated"]),
    template_id: z.string().nullable().optional(),
    parties: z.array(ContractDraftPartySchema).default([]),
    effective_date: z.string().nullable().optional(),
    expiration_date: z.string().nullable().optional(),
    total_value_usd: z.number().nullable().optional(),
    title: z.string(),
    summary: z.string(),
    body_markdown: z.string(),
    sections: z.array(ContractDraftSectionSchema).default([]),
    variables_used: z.record(z.unknown()).default({}),
    key_terms_addressed: z.record(z.string()).default({}),
    assumptions_made: z.array(ContractDraftAssumptionSchema).default([]),
    attorney_review_focus: z.array(ContractDraftAttorneyFocusSchema).default([]),
    disclaimer: z.string().default(CANONICAL_DISCLAIMER),
    citations: z.array(z.unknown()).default([]),
  })
  .passthrough();
export type ContractDraftMetadata = z.infer<typeof ContractDraftMetadataSchema>;

// ── Full draft artifact wrapper (mirrors CostSchedulePackageSchema pattern) ─
export const ContractDraftSchema = z
  .object({
    artifact_type: z.literal("contract_draft").or(z.string()).optional(),
    artifact_id: z.string().optional(),
    title: z.string().default(""),
    summary: z.string().default(""),
    body_markdown: z.string().default(""),
    ...ContractDraftMetadataSchema.shape,
  })
  .passthrough();
export type ContractDraft = z.infer<typeof ContractDraftSchema>;

// ─── Project Requests (Requests tab) ─────────────────────────────────────────

export const ProjectRequestSchema = z.object({
  id: z.string(),
  user_id: z.string(),
  message: z.string(),
  intent: z.string(), // estimate | schedule | rfi | contract | general
  status: z.string(), // processing | complete | failed
  response: z.string().nullable().optional(),
  output_module: z.string().nullable().optional(),
  output_id: z.string().nullable().optional(),
  drive_url: z.string().nullable().optional(),
  filenames: z.string().nullable().optional(), // comma-separated
  created_at: z.string(),
  updated_at: z.string(),
});
export type ProjectRequest = z.infer<typeof ProjectRequestSchema>;

export const ProjectRequestListResponseSchema = z.object({
  items: z.array(ProjectRequestSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
});
export type ProjectRequestListResponse = z.infer<typeof ProjectRequestListResponseSchema>;

export const ProjectRequestSubmitResponseSchema = z.object({
  request_id: z.string(),
  intent: z.string(),
  status: z.string(),
  message: z.string(),
});
export type ProjectRequestSubmitResponse = z.infer<typeof ProjectRequestSubmitResponseSchema>;

// ─── Sites (DataSite Intelligence) ───────────────────────────────────────────

export const SiteScoreSchema = z.object({
  power: z.number().nullable().optional(),
  fiber: z.number().nullable().optional(),
  permitting: z.number().nullable().optional(),
  environmental: z.number().nullable().optional(),
  land: z.number().nullable().optional(),
  water: z.number().nullable().optional(),
  market: z.number().nullable().optional(),
  financial: z.number().nullable().optional(),
  title: z.number().nullable().optional(),
  geotechnical: z.number().nullable().optional(),
  total_weighted: z.number().nullable().optional(),
});
export type SiteScore = z.infer<typeof SiteScoreSchema>;

export const SiteSchema = z.object({
  site_id: z.string(),
  status: z.string(),
  lead_source: z.string().nullable().optional(),
  property: z.object({
    address: z.string().nullable().optional(),
    city: z.string().nullable().optional(),
    state: z.string().nullable().optional(),
    zip: z.string().nullable().optional(),
    county: z.string().nullable().optional(),
    acres: z.number().nullable().optional(),
  }).optional().default({}),
  target_workload: z.string().nullable().optional(),
  target_mw: z.number().nullable().optional(),
  scores: z.object({
    criteria: z.record(z.object({
      score: z.number().nullable().optional(),
      weight: z.number().nullable().optional(),
      weighted_score: z.number().nullable().optional(),
    })).optional().default({}),
    total_weighted: z.number().nullable().optional(),
  }).optional().default({}),
  recommendation: z.object({
    verdict: z.string().nullable().optional(),
    summary: z.string().nullable().optional(),
    risks: z.array(z.string()).optional().default([]),
    strengths: z.array(z.string()).optional().default([]),
    next_steps: z.array(z.string()).optional().default([]),
  }).optional().default({}),
  documents: z.array(z.object({
    doc_id: z.string(),
    filename: z.string().nullable().optional(),
    type: z.string().nullable().optional(),
  })).optional().default([]),
  created_at: z.string().nullable().optional(),
  updated_at: z.string().nullable().optional(),
});
export type Site = z.infer<typeof SiteSchema>;

export const SiteListResponseSchema = z.object({
  items: z.array(SiteSchema).optional(),
  // DataSite may return a flat array directly
}).or(z.array(SiteSchema));
export type SiteListResponse = z.infer<typeof SiteListResponseSchema>;

// ─── Projects ─────────────────────────────────────────────────────────────────

export const ProjectSchema = z.object({
  id: z.string(),
  user_id: z.string(),
  name: z.string(),
  address: z.string().nullable().optional(),
  site_id: z.string().nullable().optional(),
  site_score: z.number().nullable().optional(),
  site_verdict: z.string().nullable().optional(),
  workload_type: z.string().nullable().optional(),
  phase: z.string(),
  status: z.string(),
  notes: z.string().nullable().optional(),
  // Sprint 0.2 — budget fields
  budget_usd: z.number().nullable().optional(),
  committed_usd: z.number().nullable().optional(),
  forecast_usd: z.number().nullable().optional(),
  // Sprint 0.2 — computed milestone stats (from list + detail endpoints)
  milestone_total: z.number().int().default(0),
  milestone_complete: z.number().int().default(0),
  milestone_overdue: z.number().int().default(0),
  created_at: z.string(),
  updated_at: z.string(),
});
export type QuillProject = z.infer<typeof ProjectSchema>;

export const ProjectListResponseSchema = z.object({
  items: z.array(ProjectSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
});
export type ProjectListResponse = z.infer<typeof ProjectListResponseSchema>;

export const ProjectCreateSchema = z.object({
  name: z.string(),
  address: z.string().optional(),
  site_id: z.string().optional(),
  site_score: z.number().optional(),
  site_verdict: z.string().optional(),
  workload_type: z.string().optional(),
  phase: z.string().optional(),
  status: z.string().optional(),
  notes: z.string().optional(),
});
export type ProjectCreate = z.infer<typeof ProjectCreateSchema>;

// ─── Projects Sprint 0.2 — extended project schema with budget fields ─────────

export const ProjectExtendedSchema = ProjectSchema.extend({
  budget_usd: z.number().nullable().optional(),
  committed_usd: z.number().nullable().optional(),
  forecast_usd: z.number().nullable().optional(),
});
export type QuillProjectExtended = z.infer<typeof ProjectExtendedSchema>;

// ─── Milestones ───────────────────────────────────────────────────────────────

export const ProjectMilestoneSchema = z.object({
  id: z.string(),
  project_id: z.string(),
  name: z.string(),
  description: z.string().nullable().optional(),
  due_date: z.string().nullable().optional(),  // ISO date string YYYY-MM-DD
  completed_at: z.string().nullable().optional(),
  created_at: z.string(),
});
export type ProjectMilestone = z.infer<typeof ProjectMilestoneSchema>;

export const ProjectMilestoneListSchema = z.object({
  items: z.array(ProjectMilestoneSchema),
  total: z.number().int(),
});
export type ProjectMilestoneList = z.infer<typeof ProjectMilestoneListSchema>;

// ─── Log entries ──────────────────────────────────────────────────────────────

export const LOG_ENTRY_TYPES = ["general", "issue", "milestone", "decision"] as const;
export type LogEntryType = typeof LOG_ENTRY_TYPES[number];

export const ProjectLogEntrySchema = z.object({
  id: z.string(),
  project_id: z.string(),
  user_id: z.string().nullable().optional(),
  entry_type: z.string(),  // general | issue | milestone | decision
  text: z.string(),
  created_at: z.string(),
});
export type ProjectLogEntry = z.infer<typeof ProjectLogEntrySchema>;

export const ProjectLogListSchema = z.object({
  items: z.array(ProjectLogEntrySchema),
  total: z.number().int(),
});
export type ProjectLogList = z.infer<typeof ProjectLogListSchema>;

// ─── Document links ───────────────────────────────────────────────────────────

export const ProjectDocumentLinkSchema = z.object({
  id: z.string(),
  project_id: z.string(),
  document_id: z.string().nullable().optional(),
  name: z.string(),
  url: z.string().nullable().optional(),
  created_at: z.string(),
});
export type ProjectDocumentLink = z.infer<typeof ProjectDocumentLinkSchema>;

export const ProjectDocumentLinkListSchema = z.object({
  items: z.array(ProjectDocumentLinkSchema),
  total: z.number().int(),
});
export type ProjectDocumentLinkList = z.infer<typeof ProjectDocumentLinkListSchema>;

// ─── Contract links ───────────────────────────────────────────────────────────

export const ProjectContractLinkSchema = z.object({
  id: z.string(),
  project_id: z.string(),
  contract_id: z.string(),
  created_at: z.string(),
});
export type ProjectContractLink = z.infer<typeof ProjectContractLinkSchema>;

export const ProjectContractLinkListSchema = z.object({
  items: z.array(ProjectContractLinkSchema),
  total: z.number().int(),
});
export type ProjectContractLinkList = z.infer<typeof ProjectContractLinkListSchema>;

// ─── Estimate links ───────────────────────────────────────────────────────────

export const ProjectEstimateLinkSchema = z.object({
  id: z.string(),
  project_id: z.string(),
  estimate_id: z.string(),
  created_at: z.string(),
});
export type ProjectEstimateLink = z.infer<typeof ProjectEstimateLinkSchema>;

export const ProjectEstimateLinkListSchema = z.object({
  items: z.array(ProjectEstimateLinkSchema),
  total: z.number().int(),
});
export type ProjectEstimateLinkList = z.infer<typeof ProjectEstimateLinkListSchema>;

// ─── Facility Operations — Campuses ──────────────────────────────────────────
// Sprint 1A — maps to /v1/campuses endpoints

export const CAMPUS_STATUSES = ["commissioning", "live", "maintenance", "decommissioned"] as const;
export type CampusStatus = typeof CAMPUS_STATUSES[number];

export const INCIDENT_SEVERITIES = ["P1", "P2", "P3", "P4"] as const;
export type IncidentSeverity = typeof INCIDENT_SEVERITIES[number];

export const INCIDENT_STATUSES = ["open", "investigating", "resolved", "closed"] as const;
export type IncidentStatus = typeof INCIDENT_STATUSES[number];

export const METRIC_TYPES = ["pue", "uptime_pct", "power_mw", "temp_avg", "cooling_efficiency"] as const;
export type MetricType = typeof METRIC_TYPES[number];

export const CampusSchema = z.object({
  id: z.string(),
  project_id: z.string().nullable().optional(),
  name: z.string(),
  address: z.string().nullable().optional(),
  mw_capacity: z.number().nullable().optional(),
  mw_live: z.number().nullable().optional(),
  status: z.string(),  // commissioning | live | maintenance | decommissioned
  pue_target: z.number().nullable().optional(),
  pue_current: z.number().nullable().optional(),
  uptime_pct: z.number().nullable().optional(),
  power_mw_current: z.number().nullable().optional(),
  notes: z.string().nullable().optional(),
  active_p1_p2_count: z.number().int().default(0),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Campus = z.infer<typeof CampusSchema>;

export const CampusListResponseSchema = z.object({
  items: z.array(CampusSchema),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
});
export type CampusListResponse = z.infer<typeof CampusListResponseSchema>;

export const CampusIncidentSchema = z.object({
  id: z.string(),
  campus_id: z.string(),
  severity: z.string(),  // P1 | P2 | P3 | P4
  title: z.string(),
  description: z.string().nullable().optional(),
  status: z.string(),  // open | investigating | resolved | closed
  impact: z.string().nullable().optional(),
  opened_at: z.string(),
  resolved_at: z.string().nullable().optional(),
  rca_notes: z.string().nullable().optional(),
  created_by: z.string().nullable().optional(),
  updated_at: z.string(),
});
export type CampusIncident = z.infer<typeof CampusIncidentSchema>;

export const CampusIncidentListResponseSchema = z.object({
  items: z.array(CampusIncidentSchema),
  total: z.number().int(),
});
export type CampusIncidentListResponse = z.infer<typeof CampusIncidentListResponseSchema>;

export const CampusMetricSchema = z.object({
  id: z.string(),
  campus_id: z.string(),
  metric_type: z.string(),
  value: z.number(),
  unit: z.string().nullable().optional(),
  recorded_at: z.string(),
});
export type CampusMetric = z.infer<typeof CampusMetricSchema>;

export const CampusMetricListResponseSchema = z.object({
  items: z.array(CampusMetricSchema),
  total: z.number().int(),
});
export type CampusMetricListResponse = z.infer<typeof CampusMetricListResponseSchema>;

// ─── Sprint 1B — Sales & Pipeline ────────────────────────────────────────────

export const ACCOUNT_TYPES = ["prospect", "customer"] as const;
export type AccountType = typeof ACCOUNT_TYPES[number];

export const DEAL_STAGES = ["prospect", "qualified", "proposal", "negotiating", "won", "lost"] as const;
export type DealStage = typeof DEAL_STAGES[number];

export const WORKLOAD_TYPES = ["ai_hpc", "hyperscale", "enterprise_colo", "edge", "mixed"] as const;
export type WorkloadType = typeof WORKLOAD_TYPES[number];

export const ACTIVITY_TYPES = ["call", "email", "meeting", "proposal_sent", "contract_sent", "note"] as const;
export type ActivityType = typeof ACTIVITY_TYPES[number];

// ─── Account ──────────────────────────────────────────────────────────────────

export const AccountSchema = z.object({
  id: z.string(),
  name: z.string(),
  type: z.string(),  // prospect | customer
  industry: z.string().nullable().optional(),
  website: z.string().nullable().optional(),
  hq_city: z.string().nullable().optional(),
  hq_state: z.string().nullable().optional(),
  primary_contact_name: z.string().nullable().optional(),
  primary_contact_email: z.string().nullable().optional(),
  primary_contact_phone: z.string().nullable().optional(),
  notes: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Account = z.infer<typeof AccountSchema>;

export const AccountListPageSchema = z.object({
  items: z.array(AccountSchema),
  total: z.number().int(),
});
export type AccountListPage = z.infer<typeof AccountListPageSchema>;

// ─── Deal ─────────────────────────────────────────────────────────────────────

export const DealSchema = z.object({
  id: z.string(),
  account_id: z.string(),
  name: z.string(),
  stage: z.string(),  // prospect | qualified | proposal | negotiating | won | lost
  value_usd: z.number().nullable().optional(),
  mw_required: z.number().nullable().optional(),
  workload_type: z.string().nullable().optional(),
  probability_pct: z.number().int().nullable().optional(),
  expected_close: z.string().nullable().optional(),  // ISO date YYYY-MM-DD
  campus_id: z.string().nullable().optional(),
  project_id: z.string().nullable().optional(),
  lost_reason: z.string().nullable().optional(),
  notes: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Deal = z.infer<typeof DealSchema>;

export const DealWithAccountSchema = DealSchema.extend({
  account: AccountSchema,
});
export type DealWithAccount = z.infer<typeof DealWithAccountSchema>;

export const DealListPageSchema = z.object({
  items: z.array(DealSchema),
  total: z.number().int(),
});
export type DealListPage = z.infer<typeof DealListPageSchema>;

// ─── Deal Activity ────────────────────────────────────────────────────────────

export const DealActivitySchema = z.object({
  id: z.string(),
  deal_id: z.string(),
  activity_type: z.string(),  // call | email | meeting | proposal_sent | contract_sent | note
  summary: z.string(),
  created_by: z.string().nullable().optional(),
  created_at: z.string(),
});
export type DealActivity = z.infer<typeof DealActivitySchema>;

export const DealActivityListPageSchema = z.object({
  items: z.array(DealActivitySchema),
  total: z.number().int(),
});
export type DealActivityListPage = z.infer<typeof DealActivityListPageSchema>;

// ─── Pipeline Summary ─────────────────────────────────────────────────────────

export const StageStatsSchema = z.object({
  stage: z.string(),
  count: z.number().int(),
  total_mw: z.number(),
  total_value_usd: z.number(),
});
export type StageStats = z.infer<typeof StageStatsSchema>;

export const PipelineSummarySchema = z.object({
  stages: z.array(StageStatsSchema),
  total_active_deals: z.number().int(),
  total_active_mw: z.number(),
  total_active_value_usd: z.number(),
  win_rate_pct: z.number().nullable().optional(),
});
export type PipelineSummary = z.infer<typeof PipelineSummarySchema>;

// ─── Sprint 2A — Customer Success ─────────────────────────────────────────────

export const SupportTicketSchema = z.object({
  id: z.string(),
  account_id: z.string(),
  title: z.string(),
  description: z.string().nullable().optional(),
  severity: z.enum(["P1", "P2", "P3", "P4"]),
  status: z.enum(["open", "in_progress", "resolved", "closed"]),
  resolution_notes: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
  resolved_at: z.string().nullable().optional(),
});
export type SupportTicket = z.infer<typeof SupportTicketSchema>;

export const TicketListPageSchema = z.object({
  items: z.array(SupportTicketSchema),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
});
export type TicketListPage = z.infer<typeof TicketListPageSchema>;

export const AccountNoteSchema = z.object({
  id: z.string(),
  account_id: z.string(),
  text: z.string(),
  created_by: z.string().nullable().optional(),
  created_at: z.string(),
});
export type AccountNote = z.infer<typeof AccountNoteSchema>;

export const NoteListPageSchema = z.object({
  items: z.array(AccountNoteSchema),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
});
export type NoteListPage = z.infer<typeof NoteListPageSchema>;

export const CustomerHealthSchema = z.object({
  ticket_score: z.number(),
  payment_score: z.number(),
  engagement_score: z.number(),
  total: z.number(),
  open_p1: z.number().int(),
  open_p2: z.number().int(),
  open_p3: z.number().int(),
  open_tickets_total: z.number().int(),
});
export type CustomerHealth = z.infer<typeof CustomerHealthSchema>;

export const CustomerDetailSchema = z.object({
  id: z.string(),
  name: z.string(),
  type: z.string(),
  industry: z.string().nullable().optional(),
  website: z.string().nullable().optional(),
  hq_city: z.string().nullable().optional(),
  hq_state: z.string().nullable().optional(),
  primary_contact_name: z.string().nullable().optional(),
  primary_contact_email: z.string().nullable().optional(),
  primary_contact_phone: z.string().nullable().optional(),
  notes: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
  health: CustomerHealthSchema.nullable().optional(),
  open_ticket_count: z.number().int().default(0),
  won_deal: z
    .object({
      id: z.string(),
      name: z.string(),
      stage: z.string(),
      campus_id: z.string().nullable().optional(),
      value_usd: z.number().nullable().optional(),
    })
    .nullable()
    .optional(),
});
export type CustomerDetail = z.infer<typeof CustomerDetailSchema>;

export const CustomerListPageSchema = z.object({
  items: z.array(CustomerDetailSchema),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
});
export type CustomerListPage = z.infer<typeof CustomerListPageSchema>;

export const CustomerSummarySchema = z.object({
  total_customers: z.number().int(),
  open_tickets: z.number().int(),
  has_critical_tickets: z.boolean(),
  avg_health_score: z.number().nullable().optional(),
  at_risk_count: z.number().int(),
});
export type CustomerSummary = z.infer<typeof CustomerSummarySchema>;

// ─── Supply Chain — Sprint 2B ─────────────────────────────────────────────────

export const EQUIPMENT_CATEGORIES = [
  "generator", "ups", "switchgear", "cooling", "pdu", "security", "fiber", "other",
] as const;
export type EquipmentCategory = typeof EQUIPMENT_CATEGORIES[number];

export const EQUIPMENT_STATUSES = [
  "not_ordered", "ordered", "in_transit", "received", "installed", "cancelled",
] as const;
export type EquipmentStatus = typeof EQUIPMENT_STATUSES[number];

export const VENDOR_CATEGORIES = [
  "generator", "ups", "switchgear", "cooling", "pdu", "security", "fiber",
  "construction", "other",
] as const;
export type VendorCategory = typeof VENDOR_CATEGORIES[number];

// ─── Equipment ────────────────────────────────────────────────────────────────

export const EquipmentSchema = z.object({
  id: z.string(),
  name: z.string(),
  category: z.string(),
  project_id: z.string().nullable().optional(),
  manufacturer: z.string().nullable().optional(),
  model_number: z.string().nullable().optional(),
  quantity: z.number().int(),
  unit_cost_usd: z.number().nullable().optional(),
  lead_time_weeks: z.number().int().nullable().optional(),
  order_date: z.string().nullable().optional(),       // ISO date YYYY-MM-DD
  expected_delivery: z.string().nullable().optional(), // ISO date
  actual_delivery: z.string().nullable().optional(),   // ISO date
  status: z.string(),  // not_ordered | ordered | in_transit | received | installed | cancelled
  vendor_id: z.string().nullable().optional(),
  notes: z.string().nullable().optional(),
  at_risk: z.boolean().default(false),
  total_cost_usd: z.number().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Equipment = z.infer<typeof EquipmentSchema>;

export const EquipmentListPageSchema = z.object({
  items: z.array(EquipmentSchema),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
});
export type EquipmentListPage = z.infer<typeof EquipmentListPageSchema>;

// ─── Vendor ───────────────────────────────────────────────────────────────────

export const VendorSchema = z.object({
  id: z.string(),
  name: z.string(),
  category: z.string(),
  contact_name: z.string().nullable().optional(),
  contact_email: z.string().nullable().optional(),
  contact_phone: z.string().nullable().optional(),
  website: z.string().nullable().optional(),
  prequalified: z.boolean(),
  performance_score: z.number().nullable().optional(),  // 0–10
  notes: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Vendor = z.infer<typeof VendorSchema>;

export const VendorListPageSchema = z.object({
  items: z.array(VendorSchema),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
});
export type VendorListPage = z.infer<typeof VendorListPageSchema>;

// ─── Supply Chain Summary ─────────────────────────────────────────────────────

export const SupplyChainSummarySchema = z.object({
  total_equipment_items: z.number().int(),
  total_equipment_value_usd: z.number(),
  at_risk_count: z.number().int(),
  approved_vendor_count: z.number().int(),
  vendor_count: z.number().int(),
});
export type SupplyChainSummary = z.infer<typeof SupplyChainSummarySchema>;

// ─── Finance — Sprint 3A ──────────────────────────────────────────────────────

export const BUDGET_CATEGORIES = [
  "land", "construction", "equipment", "opex", "contingency", "other",
] as const;
export type BudgetCategory = typeof BUDGET_CATEGORIES[number];

export const INVOICE_STATUSES = [
  "draft", "sent", "paid", "overdue", "cancelled",
] as const;
export type InvoiceStatus = typeof INVOICE_STATUSES[number];

export const FinanceSummarySchema = z.object({
  total_arr_usd: z.number(),
  total_pipeline_value_usd: z.number(),
  total_capex_committed_usd: z.number(),
  total_project_budget_usd: z.number(),
  total_project_forecast_usd: z.number(),
  budget_variance_usd: z.number(),
  total_outstanding_invoices_usd: z.number(),
  overdue_invoices_count: z.number().int(),
});
export type FinanceSummary = z.infer<typeof FinanceSummarySchema>;

export const ArrLineSchema = z.object({
  deal_id: z.string(),
  deal_name: z.string(),
  account_id: z.string(),
  account_name: z.string(),
  value_usd: z.number().nullable().optional(),
  mw_required: z.number().nullable().optional(),
  campus_id: z.string().nullable().optional(),
});
export type ArrLine = z.infer<typeof ArrLineSchema>;

export const ArrResponseSchema = z.object({
  items: z.array(ArrLineSchema),
  total: z.number().int(),
});
export type ArrResponse = z.infer<typeof ArrResponseSchema>;

export const CapexLineSchema = z.object({
  project_id: z.string(),
  project_name: z.string(),
  budget_usd: z.number().nullable().optional(),
  committed_usd: z.number().nullable().optional(),
  forecast_usd: z.number().nullable().optional(),
  equipment_total_usd: z.number(),
});
export type CapexLine = z.infer<typeof CapexLineSchema>;

export const CapexResponseSchema = z.object({
  items: z.array(CapexLineSchema),
  total: z.number().int(),
});
export type CapexResponse = z.infer<typeof CapexResponseSchema>;

export const BudgetLineSchema = z.object({
  id: z.string(),
  project_id: z.string().nullable().optional(),
  category: z.string(),
  description: z.string(),
  budget_usd: z.number(),
  committed_usd: z.number(),
  actual_usd: z.number(),
  period: z.string().nullable().optional(),
  notes: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type BudgetLine = z.infer<typeof BudgetLineSchema>;

export const BudgetLineListSchema = z.object({
  items: z.array(BudgetLineSchema),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
});
export type BudgetLineList = z.infer<typeof BudgetLineListSchema>;

export const InvoiceSchema = z.object({
  id: z.string(),
  account_id: z.string().nullable().optional(),
  deal_id: z.string().nullable().optional(),
  invoice_number: z.string().nullable().optional(),
  amount_usd: z.number(),
  status: z.string(),
  issue_date: z.string(),
  due_date: z.string(),
  paid_date: z.string().nullable().optional(),
  notes: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Invoice = z.infer<typeof InvoiceSchema>;

export const InvoiceListSchema = z.object({
  items: z.array(InvoiceSchema),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
});
export type InvoiceList = z.infer<typeof InvoiceListSchema>;

export const AgingBucketSchema = z.object({
  label: z.string(),
  count: z.number().int(),
  total_usd: z.number(),
});
export type AgingBucket = z.infer<typeof AgingBucketSchema>;

export const ArAgingSchema = z.object({
  buckets: z.array(AgingBucketSchema),
  total_outstanding_usd: z.number(),
  overdue_invoices_count: z.number().int(),
});
export type ArAging = z.infer<typeof ArAgingSchema>;

// ─── Intelligence — Sprint 3B ─────────────────────────────────────────────────

export const KpiSnapshotSchema = z.object({
  mw_under_site_control: z.number(),
  mw_under_construction: z.number(),
  mw_live: z.number(),
  total_arr_usd: z.number(),
  pipeline_value_usd: z.number(),
  active_incidents_p1_p2: z.number().int(),
  avg_pue: z.number().nullable().optional(),
  open_customer_tickets: z.number().int(),
  at_risk_equipment_count: z.number().int(),
  sites_in_pipeline: z.number().int(),
  active_projects: z.number().int(),
  active_customers: z.number().int(),
  computed_at: z.string(),
});
export type KpiSnapshot = z.infer<typeof KpiSnapshotSchema>;

export const ExceptionItemSchema = z.object({
  id: z.string(),
  module: z.string(),
  severity: z.string(),
  title: z.string(),
  description: z.string(),
  created_at: z.string(),
  meta: z.record(z.any()).optional().default({}),
});
export type ExceptionItem = z.infer<typeof ExceptionItemSchema>;

export const ExceptionListSchema = z.object({
  items: z.array(ExceptionItemSchema),
  total: z.number().int(),
});
export type ExceptionList = z.infer<typeof ExceptionListSchema>;

export const BriefSectionSchema = z.object({
  title: z.string(),
  summary: z.string(),
  action_items: z.array(z.string()),
});
export type BriefSection = z.infer<typeof BriefSectionSchema>;

export const BriefSchema = z.object({
  generated_at: z.string(),
  incidents: BriefSectionSchema,
  revenue: BriefSectionSchema,
  construction: BriefSectionSchema,
  sites: BriefSectionSchema,
  customers: BriefSectionSchema,
  supply_chain: BriefSectionSchema,
  action_items: BriefSectionSchema,
});
export type Brief = z.infer<typeof BriefSchema>;

export const AgentActivitySchema = z.object({
  id: z.string(),
  agent_name: z.string(),
  intent: z.string(),
  status: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  message_preview: z.string().nullable().optional(),
});
export type AgentActivity = z.infer<typeof AgentActivitySchema>;

export const AgentActivityListSchema = z.object({
  items: z.array(AgentActivitySchema),
  total: z.number().int(),
  window_hours: z.number().int(),
});
export type AgentActivityList = z.infer<typeof AgentActivityListSchema>;

// ─── Compliance Register — Sprint 4A ─────────────────────────────────────────

export const OBLIGATION_TYPES = [
  "payment", "notice", "reporting", "renewal", "termination", "other",
] as const;
export type ObligationType = typeof OBLIGATION_TYPES[number];

export const OBLIGATION_STATUSES = ["open", "complete", "overdue", "waived"] as const;
export type ObligationStatus = typeof OBLIGATION_STATUSES[number];

export const RECURRENCES = ["one_time", "monthly", "quarterly", "annual"] as const;
export type Recurrence = typeof RECURRENCES[number];

export const REGULATORY_FRAMEWORKS = [
  "ferc", "nerc", "epa", "fisma", "soc2", "iso27001", "gdpr", "ccpa", "state", "other",
] as const;
export type RegulatoryFramework = typeof REGULATORY_FRAMEWORKS[number];

export const REGULATORY_STATUSES = ["open", "complete", "in_progress", "waived"] as const;
export type RegulatoryStatus = typeof REGULATORY_STATUSES[number];

export const INSURANCE_TYPES = [
  "property", "casualty", "directors_officers", "cyber",
  "builders_risk", "professional", "other",
] as const;
export type InsuranceType = typeof INSURANCE_TYPES[number];

export const INSURANCE_STATUSES = ["active", "expiring", "expired", "cancelled"] as const;
export type InsuranceStatus = typeof INSURANCE_STATUSES[number];

export const CHECKLIST_FRAMEWORKS = ["soc2", "iso27001", "fisma", "nist", "custom"] as const;
export type ChecklistFramework = typeof CHECKLIST_FRAMEWORKS[number];

export const CHECKLIST_STATUSES = ["active", "complete", "archived"] as const;
export type ChecklistStatus = typeof CHECKLIST_STATUSES[number];

// ── Obligation ──────────────────────────────────────────────────────────────
export const ObligationSchema = z.object({
  id: z.string(),
  contract_id: z.string().nullable().optional(),
  title: z.string(),
  description: z.string().nullable().optional(),
  obligation_type: z.string(),
  due_date: z.string().nullable().optional(),
  recurrence: z.string().nullable().optional(),
  status: z.string(),
  notes: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Obligation = z.infer<typeof ObligationSchema>;

export const ObligationListPageSchema = z.object({
  items: z.array(ObligationSchema),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
});
export type ObligationListPage = z.infer<typeof ObligationListPageSchema>;

// ── Regulatory item ─────────────────────────────────────────────────────────
export const RegulatoryItemSchema = z.object({
  id: z.string(),
  title: z.string(),
  description: z.string().nullable().optional(),
  framework: z.string(),
  jurisdiction: z.string().nullable().optional(),
  due_date: z.string().nullable().optional(),
  recurrence: z.string().nullable().optional(),
  status: z.string(),
  responsible_party: z.string().nullable().optional(),
  notes: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type RegulatoryItem = z.infer<typeof RegulatoryItemSchema>;

export const RegulatoryListPageSchema = z.object({
  items: z.array(RegulatoryItemSchema),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
});
export type RegulatoryListPage = z.infer<typeof RegulatoryListPageSchema>;

// ── Insurance policy ────────────────────────────────────────────────────────
export const InsurancePolicySchema = z.object({
  id: z.string(),
  policy_name: z.string(),
  policy_type: z.string(),
  carrier: z.string().nullable().optional(),
  policy_number: z.string().nullable().optional(),
  coverage_amount_usd: z.number().nullable().optional(),
  premium_annual_usd: z.number().nullable().optional(),
  effective_date: z.string().nullable().optional(),
  expiry_date: z.string().nullable().optional(),
  status: z.string(),
  notes: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type InsurancePolicy = z.infer<typeof InsurancePolicySchema>;

export const InsuranceListPageSchema = z.object({
  items: z.array(InsurancePolicySchema),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
});
export type InsuranceListPage = z.infer<typeof InsuranceListPageSchema>;

// ── Checklist ───────────────────────────────────────────────────────────────
export const ChecklistItemSchema = z.object({
  id: z.string(),
  checklist_id: z.string(),
  control_id: z.string().nullable().optional(),
  title: z.string(),
  description: z.string().nullable().optional(),
  checked: z.boolean(),
  checked_at: z.string().nullable().optional(),
  evidence_url: z.string().nullable().optional(),
  notes: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type ChecklistItem = z.infer<typeof ChecklistItemSchema>;

export const ChecklistSchema = z.object({
  id: z.string(),
  name: z.string(),
  framework: z.string(),
  campus_id: z.string().nullable().optional(),
  status: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Checklist = z.infer<typeof ChecklistSchema>;

export const ChecklistWithItemsSchema = z.object({
  id: z.string(),
  name: z.string(),
  framework: z.string(),
  campus_id: z.string().nullable().optional(),
  status: z.string(),
  items: z.array(ChecklistItemSchema),
  total_items: z.number().int(),
  checked_items: z.number().int(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type ChecklistWithItems = z.infer<typeof ChecklistWithItemsSchema>;

export const ChecklistListPageSchema = z.object({
  items: z.array(ChecklistSchema),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
});
export type ChecklistListPage = z.infer<typeof ChecklistListPageSchema>;

// ── Compliance summary ──────────────────────────────────────────────────────
export const UpcomingDeadlineSchema = z.object({
  deadline_type: z.string(),
  id: z.string(),
  title: z.string(),
  due_date: z.string().nullable().optional(),
  days_until_due: z.number().int().nullable().optional(),
  status: z.string(),
  framework_or_type: z.string(),
});
export type UpcomingDeadline = z.infer<typeof UpcomingDeadlineSchema>;

export const ComplianceSummarySchema = z.object({
  overdue_obligations: z.number().int(),
  expiring_insurance_30d: z.number().int(),
  open_regulatory_items: z.number().int(),
  checklists_complete_pct: z.number(),
  upcoming_deadlines: z.array(UpcomingDeadlineSchema),
});
export type ComplianceSummary = z.infer<typeof ComplianceSummarySchema>;
