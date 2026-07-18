"use client";

/**
 * /journey/[projectId] — redirects to the project's current lifecycle phase.
 * Ported from the Lovable redesign (journey.$projectId.index.tsx).
 */

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { MobileShell } from "@/components/layout/MobileShell";
import { useProject } from "@/lib/api";
import { currentJourneyPhase } from "@/lib/journey";

export default function JourneyRedirectPage() {
  const params = useParams<{ projectId: string }>();
  const projectId = params.projectId;
  const router = useRouter();
  const { data: project, isLoading, isError } = useProject(projectId);

  React.useEffect(() => {
    if (project) {
      const phase = currentJourneyPhase(project);
      router.replace(`/journey/${encodeURIComponent(projectId)}/${phase}`);
    }
  }, [project, projectId, router]);

  if (isError || (!isLoading && !project)) {
    return (
      <MobileShell>
        <div className="mx-auto w-full max-w-[708px] px-4 py-10 md:max-w-4xl md:px-8">
          <div className="glass rounded-2xl p-6 text-center">
            <p className="text-body text-label-primary">Project not found.</p>
            <Link href="/" className="mt-3 inline-flex text-callout font-medium text-accent">
              Back home
            </Link>
          </div>
        </div>
      </MobileShell>
    );
  }

  return (
    <MobileShell>
      <div className="mx-auto flex w-full max-w-[708px] items-center justify-center px-5 py-16 md:max-w-4xl md:px-8">
        <Loader2 className="h-5 w-5 animate-spin text-label-tertiary" />
      </div>
    </MobileShell>
  );
}
