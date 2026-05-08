"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { MobileShell, TopBar, BackButton } from "@/components/layout/MobileShell";
import { ApprovalDetailSheet } from "@/components/queue/ApprovalDetailSheet";
import { useApproval } from "@/lib/api";
import { EmptyState } from "@/components/ui/empty-state";
import { Inbox } from "lucide-react";

/**
 * /approvals/[id] — deep-link landing page.
 *
 * Per MOBILE_UX_SPEC.md the canonical UX for an approval is the bottom-
 * sheet over /queue. But deep links from the audit log + Telegram pings
 * still hit this URL, so we render a minimal MobileShell + the detail
 * sheet auto-opened on top.
 *
 * Closing the sheet bounces back to /queue.
 */
export default function ApprovalDeepLinkPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { data: item, isLoading } = useApproval(id);
  const [open, setOpen] = React.useState(true);

  return (
    <MobileShell>
      <TopBar
        title="Approval"
        left={<BackButton href="/queue" label="Queue" />}
      />
      <div className="bg-bg-elevated min-h-[60vh] flex flex-col items-center justify-center px-6">
        {isLoading ? (
          <div className="text-callout text-label-secondary">Loading…</div>
        ) : item ? (
          <div className="text-center space-y-2 py-12">
            <div className="text-title-3 text-label-primary">
              {item.summary ?? item.workflow}
            </div>
            <div className="text-callout text-label-secondary">
              Tap below to review.
            </div>
          </div>
        ) : (
          <EmptyState
            icon={<Inbox />}
            title="Item not found."
            subtitle="This item may already be resolved or expired."
          />
        )}
      </div>
      <ApprovalDetailSheet
        approvalId={open ? id : null}
        onClose={() => {
          setOpen(false);
          // Soft return to /queue after a short tick so animation completes.
          setTimeout(() => {
            if (typeof window !== "undefined") window.history.back();
          }, 240);
        }}
      />
    </MobileShell>
  );
}
