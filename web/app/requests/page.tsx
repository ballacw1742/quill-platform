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
 *   - When an agent is selected, its intent is sent explicitly in the form
 *     payload, overriding backend auto-classification.
 *   - Optimistic UI: new request appended immediately, reconciled on poll.
 *
 * Design: matches the dark Quill theme, mirrors the dev-chat layout.
 */

import * as React from "react";
import { toast } from "sonner";
import { MessageSquare } from "lucide-react";

import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { RequestBubble } from "@/components/requests/RequestBubble";
import { ResponseBubble } from "@/components/requests/ResponseBubble";
import { RequestInput, type RequestInputValue } from "@/components/requests/RequestInput";
import { AgentSelector, AGENTS, type AgentDef } from "@/components/requests/AgentSelector";
import { useProjectRequests, useSubmitProjectRequest } from "@/lib/api";
import type { ProjectRequest } from "@/lib/schemas";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function RequestsPage() {
  const { data: listData, isLoading } = useProjectRequests();
  const submitMutation = useSubmitProjectRequest();

  // Agent selector state — default to Coordinator
  const [selectedAgent, setSelectedAgent] = React.useState<AgentDef>(AGENTS[0]);

  // Prefill text for the input (from empty-state chip clicks)
  const [prefillValue, setPrefillValue] = React.useState<string | null>(null);

  // Local optimistic requests (not yet confirmed by server)
  const [optimisticRequests, setOptimisticRequests] = React.useState<ProjectRequest[]>([]);

  const scrollRef = React.useRef<HTMLDivElement>(null);

  // Merge server requests with optimistic ones
  const serverRequests: ProjectRequest[] = listData?.items ?? [];
  const serverIds = new Set(serverRequests.map((r) => r.id));
  const pendingOptimistic = optimisticRequests.filter((r) => !serverIds.has(r.id));
  const chronologicalServer = [...serverRequests].reverse();
  const allRequests = [...chronologicalServer, ...pendingOptimistic];

  // Auto-scroll on new requests
  React.useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [allRequests.length]);

  function handleSend(value: RequestInputValue) {
    const { message, files, driveUrl } = value;
    const effectiveMessage = message.trim();

    // Build form data — include explicit intent to override auto-classification
    const formData = new FormData();
    formData.append("message", effectiveMessage);
    formData.append("intent", selectedAgent.intent);
    for (const file of files) {
      formData.append("files", file);
    }
    if (driveUrl) {
      formData.append("drive_url", driveUrl);
    }

    // Optimistic request
    const optId = `opt-${Date.now()}`;
    const optRequest: ProjectRequest = {
      id: optId,
      user_id: "",
      message: effectiveMessage,
      intent: selectedAgent.intent,
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

  // Bottom padding accounts for: input bar height (varies with chips) + nav bar
  // Chips add ~36px, so we use a generous pb to avoid clipping the thread.
  const hasChatHistory = !isLoading && allRequests.length > 0;

  return (
    <MobileShell>
      <div className="flex flex-col min-h-screen">
        <TopBar
          title="Requests"
          left={<MessageSquare className="h-5 w-5 text-accent" aria-hidden />}
        />

        {/* Agent selector — always visible below the top bar */}
        <AgentSelector selected={selectedAgent} onSelect={setSelectedAgent} />

        {/* Message list */}
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto py-4 space-y-1 pb-[240px]"
          aria-label="Project requests"
          aria-live="polite"
        >
          {isLoading ? (
            <div className="flex items-center justify-center h-40 text-label-secondary">
              Loading…
            </div>
          ) : !hasChatHistory ? (
            /* Empty state */
            <div className="flex flex-col items-center justify-center min-h-[50vh] gap-4 px-6 text-center">
              <div className="flex flex-col items-center gap-2">
                <span className="text-5xl">{selectedAgent.emoji}</span>
                <p className="text-title-2 font-semibold text-label-primary">
                  {selectedAgent.label}
                </p>
                <p className="text-body text-label-secondary max-w-xs">
                  {selectedAgent.description}. Type below or pick an example to get started.
                </p>
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
          examples={selectedAgent.examples}
          prefillValue={prefillValue}
          onPrefillConsumed={() => setPrefillValue(null)}
        />
      </div>
    </MobileShell>
  );
}
