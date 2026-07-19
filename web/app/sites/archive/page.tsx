"use client";

/**
 * /sites/archive — Archived (rejected) site evaluations.
 *
 * A site that has been evaluated and REJECTED (decision.final_verdict ===
 * "rejected") is removed from the in-progress queue on Home and lives here.
 * From here the record can be permanently deleted.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { Archive as ArchiveIcon, ArrowLeft } from "lucide-react";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { SiteCard } from "@/components/sites/SiteCard";
import { useSites } from "@/lib/api";
import { isRejectedSite } from "@/lib/sites";

export default function SitesArchivePage() {
  const router = useRouter();
  const { data: sites = [], isLoading, error } = useSites();

  const archived = React.useMemo(
    () => sites.filter(isRejectedSite),
    [sites],
  );

  const backBtn = (
    <button
      type="button"
      onClick={() => router.push("/")}
      className="text-callout flex items-center gap-1 font-semibold text-accent"
    >
      <ArrowLeft className="h-4 w-4" /> Home
    </button>
  );

  return (
    <MobileShell>
      <TopBar title="Archive" left={backBtn} />

      {error && (
        <div className="mx-auto w-full max-w-[708px] px-4 pt-3 md:max-w-4xl md:px-8">
          <div className="rounded-xl border border-danger/30 bg-danger/10 p-3 text-callout text-danger">
            Failed to load sites.
          </div>
        </div>
      )}

      {!isLoading && archived.length === 0 && !error && (
        <div className="flex flex-col items-center justify-center gap-4 px-6 pt-24">
          <ArchiveIcon className="h-12 w-12 text-label-quaternary" />
          <div className="text-center">
            <p className="mb-1 text-body font-semibold text-label-primary">
              No archived sites.
            </p>
            <p className="text-callout text-label-secondary">
              Rejected sites appear here. You can permanently delete them from a
              site’s detail page.
            </p>
          </div>
        </div>
      )}

      {archived.length > 0 && (
        <div className="mx-auto w-full max-w-[708px] px-4 pt-3 pb-8 md:max-w-4xl md:px-8">
          <p className="text-caption-1 mb-3 text-label-tertiary">
            {archived.length} rejected {archived.length === 1 ? "site" : "sites"}.
            Open a site to permanently delete it.
          </p>
          {archived.map((s) => (
            <SiteCard
              key={s.site_id}
              site={s}
              onClick={() => router.push(`/sites/${s.site_id}`)}
            />
          ))}
        </div>
      )}
    </MobileShell>
  );
}
