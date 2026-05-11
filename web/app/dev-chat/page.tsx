"use client";

/**
 * /dev-chat — "Chat with Axe" dev interface (Sprint DC.1)
 *
 * Architecture:
 *   - Hydrates history from GET /v1/dev-chat/thread on mount.
 *   - Subscribes to /ws/dev-chat for live updates (task_started, task_progress,
 *     task_completed, task_failed, task_cancelled, thread_state).
 *   - Send requires passkey re-auth via BiometricPrompt.
 *   - Turn-locked: can't send while state=in_progress; shows cancel banner.
 *
 * Tab bar note (deliberate 6-tab design):
 *   We've added a 6th tab ("Dev") which exceeds Apple's HIG recommendation
 *   of 5 tabs. This is intentional for the Quill power-user context where
 *   the dev-chat surface is a core workflow for Charles. If the HIG max
 *   becomes a real UX problem, the fix is to move "Dev" behind a "More" tab.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Terminal } from "lucide-react";

import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { DevChatMessageBubble } from "@/components/dev-chat/DevChatMessage";
import { DevChatInput } from "@/components/dev-chat/DevChatInput";
import { BiometricPrompt } from "@/components/ui/biometric-prompt";
import { useDevChatThread, useDevChatStatus, useDevChatSend, useDevChatCancel } from "@/lib/api";
import { useQueryClient } from "@tanstack/react-query";
import type { DevChatMessage, DevChatThread } from "@/lib/schemas";
import { DevChatMessageSchema } from "@/lib/schemas";

// ---------------------------------------------------------------------------
// WebSocket hook
// ---------------------------------------------------------------------------
function useDevChatSocket(onEvent: (evt: Record<string, unknown>) => void) {
  const onEventRef = React.useRef(onEvent);
  onEventRef.current = onEvent;

  React.useEffect(() => {
    if (typeof window === "undefined") return;

    const wsUrl =
      process.env.NEXT_PUBLIC_WS_URL?.replace("/ws/approvals", "/ws/dev-chat") ||
      `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws/dev-chat`;

    let cancelled = false;
    let backoff = 1000;

    const connect = () => {
      if (cancelled) return;
      const ws = new WebSocket(wsUrl);

      ws.onmessage = (msg) => {
        try {
          const data = JSON.parse(msg.data);
          onEventRef.current(data);
        } catch {
          // ignore malformed
        }
      };

      ws.onclose = () => {
        if (cancelled) return;
        setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, 30_000);
      };

      ws.onerror = () => ws.close();
    };

    connect();
    return () => {
      cancelled = true;
    };
  }, []);
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function DevChatPage() {
  const qc = useQueryClient();

  // Server state
  const { data: threadPage, isLoading } = useDevChatThread();
  const { data: statusData } = useDevChatStatus();
  const sendMutation = useDevChatSend();
  const cancelMutation = useDevChatCancel();

  // Local UI state
  const [messages, setMessages] = React.useState<DevChatMessage[]>([]);
  const [threadState, setThreadState] = React.useState<"idle" | "in_progress">("idle");
  const [currentTaskId, setCurrentTaskId] = React.useState<string | null>(null);
  const [currentMessageId, setCurrentMessageId] = React.useState<string | null>(null);

  // Passkey prompt state
  const [pendingContent, setPendingContent] = React.useState<string | null>(null);
  const [passkeyOpen, setPasskeyOpen] = React.useState(false);

  const scrollRef = React.useRef<HTMLDivElement>(null);

  // Hydrate from server
  React.useEffect(() => {
    if (threadPage) {
      setMessages(threadPage.messages);
      setThreadState(threadPage.thread.state);
    }
  }, [threadPage]);

  React.useEffect(() => {
    if (statusData) {
      setThreadState(statusData.state);
      setCurrentTaskId(statusData.current_task_id ?? null);
      setCurrentMessageId(statusData.current_message_id ?? null);
    }
  }, [statusData]);

  // Auto-scroll on new messages
  React.useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // WebSocket handler
  useDevChatSocket((evt) => {
    const type = evt.type as string;

    if (type === "thread_state") {
      setThreadState(evt.state as "idle" | "in_progress");
      if (evt.state === "idle") {
        setCurrentTaskId(null);
        setCurrentMessageId(null);
      }
      qc.invalidateQueries({ queryKey: ["dev-chat"] });
    }

    if (type === "task_started") {
      setCurrentTaskId(evt.task_id as string);
      setCurrentMessageId(evt.message_id as string);
      setThreadState("in_progress");
    }

    if (type === "task_progress") {
      // Update the streaming agent message content
      const msg = evt.message as string;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === currentMessageId
            ? { ...m, status: "streaming", content: msg }
            : m,
        ),
      );
    }

    if (type === "task_completed" || type === "task_failed" || type === "task_cancelled") {
      // Refresh from server to get final message state
      qc.invalidateQueries({ queryKey: ["dev-chat"] });
    }
  });

  // Send flow
  function handleSend(content: string) {
    setPendingContent(content);
    setPasskeyOpen(true);
  }

  function handlePasskeyConfirm(assertion: { token: string }) {
    if (!pendingContent) return;
    const content = pendingContent;
    setPendingContent(null);

    // Optimistically append user message
    const optimisticId = `opt-${Date.now()}`;
    const optimisticMsg: DevChatMessage = {
      id: optimisticId,
      thread_id: threadPage?.thread.id ?? "",
      role: "user",
      content,
      status: "completed",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimisticMsg]);
    setThreadState("in_progress");

    sendMutation.mutate(
      { content, auth_assertion: assertion.token },
      {
        onSuccess: (data) => {
          setCurrentTaskId(data.task_id);
          setCurrentMessageId(data.message_id);
          // Add placeholder agent message
          const agentPlaceholder: DevChatMessage = {
            id: data.message_id,
            thread_id: threadPage?.thread.id ?? "",
            role: "agent",
            content: "",
            status: "queued",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          };
          setMessages((prev) => [...prev, agentPlaceholder]);
          qc.invalidateQueries({ queryKey: ["dev-chat"] });
        },
        onError: (err) => {
          // Roll back optimistic update
          setMessages((prev) => prev.filter((m) => m.id !== optimisticId));
          setThreadState("idle");
          // Don't dump multi-line zod / fetch error walls into a toast.
          // Pull a short reason and log the rest to console for debugging.
          const raw = (err?.message ?? "").trim();
          const firstLine = raw.split(/\n|\. /)[0].slice(0, 160);
          if (raw.includes("409")) {
            toast.error("Axe is already working on something. Wait for it to finish.");
          } else if (raw.includes("401")) {
            toast.error("Re-authentication required. Try the passkey again.");
          } else if (firstLine.length > 0) {
            toast.error(`Failed to send: ${firstLine}`);
          } else {
            toast.error("Failed to send. Try again.");
          }
          // Full error preserved in console for postmortems
          // eslint-disable-next-line no-console
          console.error("[dev-chat] send failed:", err);
        },
      },
    );
  }

  function handleCancel(taskId: string) {
    // Use dev fallback auth — cancel doesn't need strong passkey in v1
    cancelMutation.mutate(
      { task_id: taskId, auth_assertion: "dev-cancel" },
      {
        onSuccess: () => {
          setThreadState("idle");
          setCurrentTaskId(null);
          toast.success("Task cancelled.");
        },
        onError: (err) => toast.error(`Cancel failed: ${err.message}`),
      },
    );
  }

  return (
    <MobileShell>
      <div className="flex flex-col min-h-screen">
        <TopBar
          title="Chat with Axe"
          left={<Terminal className="h-5 w-5 text-accent" aria-hidden />}
        />

        {/* Message list — bottom padding leaves room for the fixed input bar
            (~76px input + 49px tab bar + safe area). */}
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto py-4 space-y-1 pb-[140px]"
          aria-label="Dev chat messages"
          aria-live="polite"
        >
          {isLoading ? (
            <div className="flex items-center justify-center h-32 text-label-secondary">
              Loading…
            </div>
          ) : messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-32 gap-2 text-label-secondary px-8 text-center">
              <Terminal className="h-8 w-8 text-label-tertiary" />
              <p className="text-body">Tell Axe what to change in Quill.</p>
              <p className="text-caption-1 text-label-tertiary">
                Changes are committed and deployed automatically.
              </p>
            </div>
          ) : (
            messages.map((msg) => (
              <DevChatMessageBubble key={msg.id} message={msg} />
            ))
          )}
        </div>

        {/* Input */}
        <DevChatInput
          state={threadState}
          currentTaskId={currentTaskId}
          onSend={handleSend}
          onCancel={handleCancel}
          isSubmitting={sendMutation.isPending}
        />
      </div>

      {/* Passkey prompt */}
      <BiometricPrompt
        open={passkeyOpen}
        onOpenChange={setPasskeyOpen}
        title="Confirm change request"
        description="Axe will modify code and commit. Authenticate to proceed."
        actionIntent={{
          approval_id: `dev-chat:send`,
          decision: "approve",
        }}
        onConfirm={handlePasskeyConfirm}
      />
    </MobileShell>
  );
}
