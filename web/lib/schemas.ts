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
    schedule_level: z.number().int().min(1).max(5).default(1),
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

