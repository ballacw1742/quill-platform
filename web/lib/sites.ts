import type { Site } from "@/lib/schemas";

/**
 * Site queue/archive predicates — single source of truth so Home, the sites
 * board, and the Archive view agree on what "in progress" vs "archived" means.
 *
 * A site's human decision lives in site.decision.final_verdict:
 *   - "rejected"  → archived (removed from the in-progress queue)
 *   - "accepted"  → decided/advanced (its project carries it forward)
 *   -  null       → not yet decided (still in progress if not yet decided-status)
 */

export function siteFinalVerdict(site: Site): string | null {
  const d = (site as { decision?: { final_verdict?: string | null } }).decision;
  return d?.final_verdict ?? null;
}

/** A site that was evaluated and rejected by a human — lives in the Archive. */
export function isRejectedSite(site: Site): boolean {
  return siteFinalVerdict(site) === "rejected";
}

/**
 * Sites still moving through evaluation — shown in the Home "in progress"
 * queue. Excludes decided sites (accepted/advanced) and rejected/archived
 * sites.
 */
export function isSiteInProgress(site: Site): boolean {
  const status = site.status ?? "intake";
  if (status === "decided") return false; // accepted or rejected → out of queue
  if (isRejectedSite(site)) return false; // belt-and-suspenders
  return true;
}
