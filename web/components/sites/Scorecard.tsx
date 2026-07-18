"use client";

/**
 * Scorecard — per-criterion scoring table for a site evaluation.
 * Visual layer ported from quill-platform-builder/src/components/quill/sites/Scorecard.tsx.
 * Wired to prod Site type from @/lib/schemas.
 */

import type { Site } from "@/lib/schemas";

// Criteria with default weights (matches prod's scoring engine and Lovable Scorecard)
const CRITERIA: { key: string; label: string; weight: number }[] = [
  { key: "power",         label: "Power",               weight: 0.30 },
  { key: "fiber",         label: "Fiber & Connectivity", weight: 0.15 },
  { key: "permitting",    label: "Permitting",           weight: 0.15 },
  { key: "environmental", label: "Environmental",        weight: 0.15 },
  { key: "land",          label: "Land",                 weight: 0.10 },
  { key: "water",         label: "Water",                weight: 0.05 },
  { key: "market",        label: "Market",               weight: 0.05 },
  { key: "financial",     label: "Financial",            weight: 0.03 },
  { key: "title",         label: "Title",                weight: 0.01 },
  { key: "geotechnical",  label: "Geotechnical",         weight: 0.01 },
];

export function Scorecard({ site }: { site: Site }) {
  const criteria = site.scores?.criteria ?? {};

  return (
    <div className="glass rounded-2xl border border-hairline p-5">
      <p className="text-callout mb-4 font-semibold text-label-primary">Scorecard</p>
      <div className="-mx-5 overflow-x-auto">
        <table className="text-caption-1 w-full min-w-[400px]">
          <thead>
            <tr className="border-b border-hairline">
              <th className="py-2 pl-5 pr-2 text-left font-semibold text-label-secondary">Criterion</th>
              <th className="px-2 py-2 text-right font-semibold text-label-secondary">Score</th>
              <th className="px-2 py-2 text-right font-semibold text-label-secondary">Weight</th>
              <th className="py-2 pl-2 pr-5 text-right font-semibold text-label-secondary">Weighted</th>
            </tr>
          </thead>
          <tbody>
            {CRITERIA.map((c) => {
              const entry = criteria[c.key] ?? { score: null, weight: c.weight, weighted_score: null };
              const score = entry.score ?? null;
              const weight = entry.weight ?? c.weight;
              const weighted = entry.weighted_score ?? (score != null ? score * weight : null);
              return (
                <tr key={c.key} className="border-b border-hairline last:border-0">
                  <td className="py-2.5 pl-5 pr-2">
                    <span className="text-label-primary">{c.label}</span>
                  </td>
                  <td className="px-2 py-2.5 text-right">
                    {score != null ? (
                      <span className="tabular-nums text-label-primary">{score.toFixed(1)}</span>
                    ) : (
                      <span className="text-label-quaternary">—</span>
                    )}
                  </td>
                  <td className="px-2 py-2.5 text-right tabular-nums text-label-secondary">
                    {(weight * 100).toFixed(0)}%
                  </td>
                  <td className="py-2.5 pl-2 pr-5 text-right">
                    {weighted != null ? (
                      <span className="tabular-nums font-medium text-label-primary">
                        {weighted.toFixed(2)}
                      </span>
                    ) : (
                      <span className="text-label-quaternary">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
