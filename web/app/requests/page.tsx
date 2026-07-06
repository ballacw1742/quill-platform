"use client";

/**
 * /requests — Requests command center (UI redesign Phase 3, brief §5).
 *
 * Layout, top to bottom:
 *   - Large-title header ("Requests") — iOS look, matches Phase 1+2.
 *   - AgentSelector — explicit agent override (unchanged behavior).
 *   - Action catalog — all 15 modules with tappable action chips sourced
 *     from the live agent registry (GET /v1/agents). Tapping a chip
 *     pre-fills + focuses the composer with a prompt template and carries
 *     an explicit intent for POST /v1/requests.
 *   - Recent requests thread (unchanged functionally).
 *   - Universal composer — fixed above the FloatingHomeButton (geometry
 *     preserved from the Phase 2 no-overlap audit).
 *
 * Submit flow (unchanged contract):
 *   - POST /v1/requests (multipart form) with message/files/drive_url and
 *     an explicit `intent` — from the tapped chip when present, else the
 *     selected agent.
 *   - Hydrates history from GET /v1/requests; polls every 5s.
 *   - Optimistic UI: new request appended immediately, reconciled on poll.
 */

import * as React from "react";
import { toast } from "sonner";

import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { RequestBubble } from "@/components/requests/RequestBubble";
import { ResponseBubble } from "@/components/requests/ResponseBubble";
import { RequestInput, type RequestInputValue } from "@/components/requests/RequestInput";
import { AgentSelector, AGENTS, type AgentDef } from "@/components/requests/AgentSelector";
import { ActionCatalog } from "@/components/requests/ActionCatalog";
import type { CatalogChip } from "@/lib/requests/catalog";
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

  // Prefill text for the composer (from action-catalog chip taps)
  const [prefillValue, setPrefillValue] = React.useState<string | null>(null);

  // Explicit intent from the last tapped chip. Overrides the selector's
  // intent on send; cleared on send or when the user picks an agent manually.
  const [chipIntent, setChipIntent] = React.useState<string | null>(null);

  // Local optimistic requests (not yet confirmed by server)
  const [optimisticRequests, setOptimisticRequests] = React.useState<ProjectRequest[]>([]);

  const threadEndRef = React.useRef<HTMLDivElement>(null);

  // Merge server requests with optimistic ones
  const serverRequests: ProjectRequest[] = listData?.items ?? [];
  const serverIds = new Set(serverRequests.map((r) => r.id));
  const pendingOptimistic = optimisticRequests.filter((r) => !serverIds.has(r.id));
  const chronologicalServer = [...serverRequests].reverse();
  const allRequests = [...chronologicalServer, ...pendingOptimistic];

  function scrollThreadIntoView() {
    requestAnimationFrame(() => {
      threadEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    });
  }

  function handleChipTap(chip: CatalogChip) {
    setPrefillValue(chip.template);
    setChipIntent(chip.intent);
    // Keep the selector honest: show the matching agent when one exists,
    // otherwise fall back to Coordinator (the explicit chip intent still
    // routes the request to the right specialist).
    const match = AGENTS.find((a) => a.intent === chip.intent);
    setSelectedAgent(match ?? AGENTS[0]);
  }

  function handleAgentSelect(agent: AgentDef) {
    setSelectedAgent(agent);
    setChipIntent(null); // manual choice wins over the last chip tap
  }

  function handleSend(value: RequestInputValue) {
    const { message, files, driveUrl } = value;
    const effectiveMessage = message.trim();
    const intent = chipIntent ?? selectedAgent.intent;
    setChipIntent(null);

    // Build form data — include explicit intent to override auto-classification
    const formData = new FormData();
    formData.append("message", effectiveMessage);
    formData.append("intent", intent);
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
      intent,
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
    scrollThreadIntoView();

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
  const hasChatHistory = !isLoading && allRequests.length > 0;

  return (
    <MobileShell>
      <div className="flex flex-col min-h-screen">
        {/* Non-sticky hero: the large title scrolls away (iOS pattern) so the
            long catalog never slides underneath a pinned translucent header. */}
        <TopBar hero sticky={false} title="Requests" />

        {/* Agent selector — explicit override, always visible below the bar */}
        <AgentSelector selected={selectedAgent} onSelect={handleAgentSelect} />

        {/* Content: action catalog + request thread. Bottom padding clears
            the fixed composer (which itself sits above the Home button). */}
        <div className="flex-1 py-4 pb-[240px]" aria-label="Project requests">
          {/* Action catalog — every module's agents, one screen (brief §5) */}
          <ActionCatalog onChipTap={handleChipTap} />

          {/* Recent requests */}
          <div className="mt-4" aria-live="polite">
            {isLoading ? (
              <div className="flex items-center justify-center h-24 text-label-secondary">
                Loading…
              </div>
            ) : !hasChatHistory ? (
              <p className="px-6 py-6 text-center text-footnote text-label-secondary">
                No requests yet — tap an action above or type below to get started.
              </p>
            ) : (
              <>
                <h2 className="px-4 pb-1 text-title-3 font-semibold text-label-primary">
                  Recent requests
                </h2>
                <div className="space-y-1">
                  {allRequests.map((req) => (
                    <React.Fragment key={req.id}>
                      <RequestBubble request={req} />
                      <ResponseBubble request={req} />
                    </React.Fragment>
                  ))}
                </div>
              </>
            )}
            {/* scroll-mb keeps scrollIntoView targets clear of the fixed composer */}
            <div ref={threadEndRef} aria-hidden className="scroll-mb-[260px]" />
          </div>
        </div>

        {/* Fixed bottom composer — geometry unchanged (above Home button) */}
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
