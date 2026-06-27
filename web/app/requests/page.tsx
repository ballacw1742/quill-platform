"use client";

/**
 * /requests — Requests chat tab (Requests sprint)
 *
 * A chat-first interface where users submit project requests (estimates,
 * schedules, RFIs, contracts) via text or document upload. The system
 * classifies intent and routes to the appropriate existing module.
 *
 * Architecture:
 *   - Hydrates request history from GET /v1/requests on mount.
 *   - Polls every 5s (via useProjectRequests refetchInterval) so processing
 *     requests update in-place without a manual refresh.
 *   - Submit via POST /v1/requests (multipart form).
 *   - Optimistic UI: new request appended immediately, reconciled on poll.
 *
 * Design: matches the dark Quill theme, mirrors the dev-chat layout.
 */

import * as React from "react";
import { toast } from "sonner";
import { MessageSquare, ClipboardList, Calculator, CalendarDays, FileSignature } from "lucide-react";

import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { RequestBubble } from "@/components/requests/RequestBubble";
import { ResponseBubble } from "@/components/requests/ResponseBubble";
import { RequestInput, type RequestInputValue } from "@/components/requests/RequestInput";
import { useProjectRequests, useSubmitProjectRequest } from "@/lib/api";
import type { ProjectRequest } from "@/lib/schemas";

// ---------------------------------------------------------------------------
// Quick-action chips shown in the empty state
// ---------------------------------------------------------------------------
const QUICK_ACTIONS = [
  { label: "Submit RFI", icon: ClipboardList, prompt: "I need to submit an RFI for a question on the drawings." },
  { label: "Request Estimate", icon: Calculator, prompt: "I need a cost estimate for a scope change." },
  { label: "Review Schedule", icon: CalendarDays, prompt: "I need to review the project schedule and identify critical path issues." },
  { label: "Review Contract", icon: FileSignature, prompt: "I need to review a contract for risks and key terms." },
] as const;

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function RequestsPage() {
  const { data: listData, isLoading } = useProjectRequests();
  const submitMutation = useSubmitProjectRequest();

  // Local optimistic requests (not yet confirmed by server)
  const [optimisticRequests, setOptimisticRequests] = React.useState<ProjectRequest[]>([]);
  const [inputMessage, setInputMessage] = React.useState<string | null>(null);

  const scrollRef = React.useRef<HTMLDivElement>(null);

  // Merge server requests with optimistic ones
  const serverRequests: ProjectRequest[] = listData?.items ?? [];
  // Remove optimistic entries that are now in server list
  const serverIds = new Set(serverRequests.map((r) => r.id));
  const pendingOptimistic = optimisticRequests.filter((r) => !serverIds.has(r.id));
  // Render server requests in chronological order (API returns desc, so reverse)
  const chronologicalServer = [...serverRequests].reverse();
  const allRequests = [...chronologicalServer, ...pendingOptimistic];

  // Auto-scroll on new requests
  React.useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [allRequests.length]);

  // Pre-populate input if a quick action was clicked
  const [prefillMessage, setPrefillMessage] = React.useState<string | null>(null);

  function handleQuickAction(prompt: string) {
    setPrefillMessage(prompt);
  }

  function handleSend(value: RequestInputValue) {
    const { message, files, driveUrl } = value;

    // Build form data
    const formData = new FormData();
    formData.append("message", message || prefillMessage || "");
    for (const file of files) {
      formData.append("files", file);
    }
    if (driveUrl) {
      formData.append("drive_url", driveUrl);
    }

    const effectiveMessage = message || prefillMessage || "";
    setPrefillMessage(null);

    // Optimistic request
    const optId = `opt-${Date.now()}`;
    const optRequest: ProjectRequest = {
      id: optId,
      user_id: "",
      message: effectiveMessage,
      intent: "general",
      status: "processing",
      response: null,
      output_module: null,
      output_id: null,
      drive_url: driveUrl || null,
      filenames: files.length > 0 ? files.map((f) => f.name).join(",") : null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    setOptimisticRequests((prev) => [...prev, optRequest]);

    submitMutation.mutate(formData, {
      onSuccess: () => {
        // Remove optimistic — the next poll will show the real one
        setOptimisticRequests((prev) => prev.filter((r) => r.id !== optId));
      },
      onError: (err) => {
        setOptimisticRequests((prev) => prev.filter((r) => r.id !== optId));
        const raw = (err?.message ?? "").trim();
        const firstLine = raw.split(/\n|\. /)[0].slice(0, 160);
        toast.error(firstLine.length > 0 ? `Failed to submit: ${firstLine}` : "Failed to submit. Try again.");
        console.error("[requests] submit failed:", err);
      },
    });
  }

  const isProcessing = submitMutation.isPending;

  return (
    <MobileShell>
      <div className="flex flex-col min-h-screen">
        <TopBar
          title="Requests"
          left={<MessageSquare className="h-5 w-5 text-accent" aria-hidden />}
        />

        {/* Message list */}
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto py-4 space-y-1 pb-[140px]"
          aria-label="Project requests"
          aria-live="polite"
        >
          {isLoading ? (
            <div className="flex items-center justify-center h-40 text-label-secondary">
              Loading…
            </div>
          ) : allRequests.length === 0 ? (
            /* Empty state */
            <div className="flex flex-col items-center justify-center min-h-[60vh] gap-6 px-6 text-center">
              <div className="flex flex-col items-center gap-2">
                <MessageSquare className="h-10 w-10 text-label-tertiary" aria-hidden />
                <p className="text-title-2 font-semibold text-label-primary">
                  What do you need help with?
                </p>
                <p className="text-body text-label-secondary max-w-xs">
                  Submit a project request — estimates, schedules, RFIs, or contracts — and Quill routes it to the right agent.
                </p>
              </div>

              {/* Quick action chips */}
              <div className="flex flex-wrap justify-center gap-2 max-w-sm">
                {QUICK_ACTIONS.map(({ label, icon: Icon, prompt }) => (
                  <button
                    key={label}
                    type="button"
                    onClick={() => handleQuickAction(prompt)}
                    className="flex items-center gap-2 rounded-full border border-separator bg-bg-elevated px-4 py-2 text-body text-label-primary active:bg-bg-secondary transition-colors"
                  >
                    <Icon className="h-4 w-4 text-accent" aria-hidden />
                    {label}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            /* Request thread */
            allRequests.map((req) => (
              <React.Fragment key={req.id}>
                <RequestBubble request={req} />
                <ResponseBubble request={req} />
              </React.Fragment>
            ))
          )}
        </div>

        {/* Fixed bottom input */}
        <RequestInput
          onSend={handleSend}
          isProcessing={isProcessing}
        />
      </div>
    </MobileShell>
  );
}
