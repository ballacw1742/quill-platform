"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Inbox, Loader2 } from "lucide-react";
import { MobileShell, TopBar, BackButton } from "@/components/layout/MobileShell";
import { ApprovalDetailSheet } from "@/components/queue/ApprovalDetailSheet";
import { useApproval } from "@/lib/api";

/**
 * /approvals/[id] — deep-link landing page.
 *
 * Lovable-reskinned: wider content container, Loader2 spinner, "Back to queue"
 * link in the not-found state. The canonical UX for an approval is the bottom-
 * sheet over /queue, but deep links from the audit log + Telegram pings still
 * hit this URL, so we render a minimal MobileShell + the detail sheet auto-opened.
 *
 * Closing the sheet bounces back to /queue.
 *
 * PRESERVED:
 *   - ApprovalDetailSheet with full prod decision flow (useDecide, passkey,
 *     dual-sig gating, edit-then-approve, escalate, audit trail)
 *   - useApproval() from @/lib/api
 *   - No socket subscription here — MobileShell carries useApprovalsSocket()
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
      <div className="mx-auto w-full max-w-[708px] px-4 pt-4 md:max-w-4xl md:px-8">
        {isLoading ? (
          <div
            role="status"
            aria-busy="true"
            aria-label="Loading item"
            className="flex items-center justify-center gap-2 py-16 text-label-secondary"
          >
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="text-callout">Loading approval…</span>
          </div>
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
          <div className="flex flex-col items-center gap-2 rounded-2xl border border-hairline bg-bg-elevated px-6 py-12 text-center shadow-card">
            <Inbox className="h-6 w-6 text-label-tertiary" />
            <div className="text-headline text-label-primary">Item not found.</div>
            <div className="text-footnote text-label-secondary">
              This item may already be resolved or expired.
            </div>
            <Link
              href="/queue"
              className="mt-3 inline-flex h-9 items-center rounded-full bg-bg px-4 text-footnote font-semibold text-label-primary border border-hairline"
            >
              Back to queue
            </Link>
          </div>
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
