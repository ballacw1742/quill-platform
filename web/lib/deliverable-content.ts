/**
 * deliverable-content.ts
 *
 * Pure helpers for detecting deliverable content types and extracting
 * renderable data from the deliverable's `content` JSON blob.
 *
 * Keeping these as pure functions (no React/DOM) makes them unit-testable
 * in the vitest node environment alongside artifact-view.test.ts.
 *
 * Renderable type taxonomy:
 *   "doc"     — content.text | content.summary | content.markdown (string)
 *   "sheet"   — content.rows (array of arrays) [sparse table]
 *   "kv"      — content is a flat-ish object (structured artifact)
 *   "empty"   — null/undefined content
 */

export type ContentRenderKind = "doc" | "sheet" | "kv" | "empty";

/** Detect the best way to render a deliverable's content blob. */
export function detectContentKind(
  content: Record<string, unknown> | null | undefined,
): ContentRenderKind {
  if (!content || typeof content !== "object") return "empty";

  // Sheet: has a `rows` field that is an array of arrays
  if (
    Array.isArray(content.rows) &&
    content.rows.length > 0 &&
    Array.isArray(content.rows[0])
  ) {
    return "sheet";
  }

  // Doc: has a primary text/prose field
  if (
    typeof content.text === "string" ||
    typeof content.summary === "string" ||
    typeof content.markdown === "string" ||
    typeof content.body_markdown === "string"
  ) {
    return "doc";
  }

  // KV fallback for any other non-empty object
  return "kv";
}

/** Extract the primary text string from a doc-type content blob. */
export function extractDocText(
  content: Record<string, unknown>,
): string {
  return (
    (content.markdown as string) ??
    (content.body_markdown as string) ??
    (content.text as string) ??
    (content.summary as string) ??
    ""
  );
}

/**
 * Extract sheet rows from a sheet-type content blob.
 * Returns rows as string[][] (cells coerced to string for rendering).
 */
export function extractSheetRows(
  content: Record<string, unknown>,
): string[][] {
  const raw = content.rows;
  if (!Array.isArray(raw)) return [];
  return (raw as unknown[][]).map((row) =>
    Array.isArray(row) ? row.map((cell) => String(cell ?? "")) : [],
  );
}

/**
 * Extract displayable key-value pairs from a kv-type content blob.
 * Skips internal/system keys that aren't useful in the UI.
 */
const KV_SKIP_KEYS = new Set(["rows", "drive"]);

export function extractKVPairs(
  content: Record<string, unknown>,
): { key: string; value: string }[] {
  return Object.entries(content)
    .filter(([k]) => !KV_SKIP_KEYS.has(k))
    .map(([k, v]) => ({
      key: k,
      value:
        typeof v === "string"
          ? v
          : typeof v === "number" || typeof v === "boolean"
            ? String(v)
            : JSON.stringify(v, null, 2),
    }));
}

/**
 * Determine if a deliverable is in a co-development awaiting-human gate.
 * Returns true only when status === "awaiting_human" AND
 * meta.hitl_kind === "co_development".
 */
export function isCodevGate(
  status: string,
  meta: Record<string, unknown> | null | undefined,
): boolean {
  return status === "awaiting_human" && meta?.hitl_kind === "co_development";
}

/**
 * Build a human-readable diff summary between two content blobs.
 * Simple approach: serialize both, split to lines, return added/removed lines.
 * Used for the "before/after" proposal preview in the co-dev panel.
 */
export type ContentDiff = {
  before: string;
  after: string;
};

export function diffContent(
  current: Record<string, unknown> | null | undefined,
  proposed: Record<string, unknown>,
): ContentDiff {
  const before = JSON.stringify(current ?? {}, null, 2);
  const after = JSON.stringify(proposed, null, 2);
  return { before, after };
}
