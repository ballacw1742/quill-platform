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

/**
 * A site whose background evaluation has finished and is now waiting for the
 * human accept/reject decision. Mirrors the decision gate on the site detail
 * page: evaluated (has a score or verdict, or reached review/scored) AND no
 * final_verdict recorded yet. Used to surface "Awaiting decision" + a quick
 * reject affordance on the Home queue so the user doesn't have to drill into
 * the detail page to find it.
 */
export function isSiteAwaitingDecision(site: Site): boolean {
  if (siteFinalVerdict(site) != null) return false; // already accepted/rejected
  const status = site.status ?? "intake";
  if (status === "researching" || status === "scoring" || status === "intake")
    return false; // still in flight (or not yet evaluated)
  const scores = (site as { scores?: { total_weighted?: unknown } }).scores;
  const hasScore = typeof scores?.total_weighted === "number";
  const hasVerdict = !!(site as { recommendation?: { verdict?: string | null } })
    .recommendation?.verdict;
  return hasScore || hasVerdict || status === "review" || status === "scored";
}
