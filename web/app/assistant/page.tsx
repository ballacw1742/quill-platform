"use client";

/**
 * /assistant — Agent Cloud web chat (Sprint A5, agent-cloud/WEBCHAT.md).
 *
 * Surfaces the tenant's agent-cloud agents ("personal" + "quill") behind the
 * Quill API bridge:
 *   - agent picker (segmented control)
 *   - session list (sheet) + new session
 *   - streaming chat (SSE: text deltas, tool start/ok/denied chips) with a
 *     graceful non-stream fallback
 *   - budget_exceeded renders as a notice, never an error state
 */

import * as React from "react";
import { BarChart3, History, Link2, Plus, Sparkles, Wrench } from "lucide-react";
import { toast } from "sonner";

import { BackButton, MobileShell, TopBar } from "@/components/layout/MobileShell";
import {
  AssistantBubble,
  BudgetNotice,
  SystemRow,
  UserBubble,
  type ToolChip,
} from "@/components/assistant/AssistantMessage";
import { AssistantInput } from "@/components/assistant/AssistantInput";
import { Onboarding } from "@/components/assistant/Onboarding";
import { SegmentedControl } from "@/components/ui/segmented-control";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  nonStreamFallback,
  renderableMessages,
  sendAgentChat,
  useAgentCloudAgents,
  useAgentCloudSessions,
  useAgentCloudTranscript,
  useInvalidateAgentCloud,
  AgentCloudError,
  type RenderableItem,
} from "@/lib/agent-cloud";

const AGENT_LABELS: Record<string, string> = {
  personal: "Personal",
  quill: "Quill",
};

type ChatItem =
  | (RenderableItem & { kind: "user" | "system" })
  | { kind: "assistant"; text: string; tools: ToolChip[]; created_at: string; budget?: boolean };

type LiveTurn = {
  user: string;
  text: string;
  chips: ToolChip[];
  sessionId: string | null;
};

function fromRenderable(items: RenderableItem[]): ChatItem[] {
  return items.map((it) =>
    it.kind === "assistant"
      ? {
          kind: "assistant",
          text: it.text,
          tools: it.tools.map((name) => ({ name, status: "ok" as const })),
          created_at: it.created_at,
          // Persisted budget refusals read like normal assistant text; the
          // live-notice styling only applies to the in-flight turn.
        }
      : it,
  );
}

export default function AssistantPage() {
  const [agentId, setAgentId] = React.useState<string>("personal");
  const [sessionId, setSessionId] = React.useState<string | null>(null);
  const [items, setItems] = React.useState<ChatItem[]>([]);
  const [live, setLive] = React.useState<LiveTurn | null>(null);
  const [sheetOpen, setSheetOpen] = React.useState(false);
  // Session id whose transcript already hydrated `items` (guards against a
  // mid-stream transcript fetch clobbering optimistic bubbles).
  const loadedRef = React.useRef<string | null>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);

  const agents = useAgentCloudAgents();
  const sessions = useAgentCloudSessions(agentId);
  const invalidate = useInvalidateAgentCloud();
  const needTranscript = !!sessionId && loadedRef.current !== sessionId;
  const transcript = useAgentCloudTranscript(needTranscript ? sessionId : null);

  // Hydrate items when a picked session's transcript arrives.
  React.useEffect(() => {
    const data = transcript.data;
    if (!data || data.session_id !== sessionId) return;
    if (loadedRef.current === sessionId) return;
    loadedRef.current = data.session_id;
    setItems(fromRenderable(renderableMessages(data.messages)));
  }, [transcript.data, sessionId]);

  // Auto-scroll on new content.
  React.useEffect(() => {
    scrollRef.current?.scrollIntoView({ block: "end" });
  }, [items, live?.text, live?.chips.length]);

  const agentOptions = React.useMemo(() => {
    const list = agents.data?.items?.filter((a) => a.enabled) ?? [];
    if (list.length === 0) {
      return [{ value: "personal", label: "Personal" }, { value: "quill", label: "Quill" }];
    }
    return list.map((a) => ({
      value: a.agent_id,
      label: AGENT_LABELS[a.agent_id] ?? a.agent_id,
    }));
  }, [agents.data]);

  function resetTo(agent: string, session: string | null) {
    setAgentId(agent);
    setSessionId(session);
    setItems([]);
    setLive(null);
    loadedRef.current = null;
  }

  async function handleSend(text: string) {
    if (live) return;
    // Mutable turn record; mirrored into state via setLive({...turn}) so
    // React strict-mode double-invocation can never duplicate items.
    const turn: LiveTurn = { user: text, text: "", chips: [], sessionId };
    setLive({ ...turn });

    const args = { agentId, message: text, sessionId };
    let budget = false;
    let finalText = "";
    let sawError: string | null = null;

    const onEvent = (ev: Parameters<Parameters<typeof sendAgentChat>[1]["onEvent"]>[0]) => {
      if (ev.type === "session") {
        // A brand-new session: mark it hydrated so the transcript query
        // doesn't overwrite the optimistic bubbles mid-turn.
        loadedRef.current = ev.session_id;
        turn.sessionId = ev.session_id;
        setSessionId(ev.session_id);
      } else if (ev.type === "text") {
        turn.text += ev.delta;
      } else if (ev.type === "tool") {
        const idx = turn.chips.findIndex(
          (c) => c.name === ev.name && c.status === "start",
        );
        if (ev.status === "start" || idx === -1) {
          turn.chips = [...turn.chips, { name: ev.name, status: ev.status }];
        } else {
          turn.chips = turn.chips.map((c, i) =>
            i === idx ? { name: ev.name, status: ev.status } : c,
          );
        }
      } else if (ev.type === "done") {
        budget = ev.result.budget_exceeded;
        finalText = ev.result.reply;
      } else if (ev.type === "error") {
        sawError = ev.detail;
      }
      setLive({ ...turn });
    };

    try {
      await sendAgentChat(args, { onEvent });
    } catch (e) {
      if (e instanceof AgentCloudError) {
        sawError = e.message;
      } else {
        // Transport hiccup before/while streaming — try the non-stream path.
        try {
          await nonStreamFallback(args, { onEvent });
        } catch (e2) {
          sawError =
            e2 instanceof AgentCloudError ? e2.message : "Connection failed. Try again.";
        }
      }
    }

    const finalChips: ToolChip[] = turn.chips.map((c) =>
      c.status === "start" ? { ...c, status: "ok" as const } : c,
    );
    const now = new Date().toISOString();
    const next: ChatItem[] = [{ kind: "user", text: turn.user, created_at: now }];
    if (sawError) {
      next.push({ kind: "system", text: `Error: ${sawError}`, created_at: now });
    } else {
      next.push({
        kind: "assistant",
        text: finalText || turn.text,
        tools: finalChips,
        created_at: now,
        ...(budget ? { budget: true } : {}),
      });
    }
    setItems((prev) => [...prev, ...next]);
    setLive(null);

    if (sawError) toast.error(sawError);
    invalidate(turn.sessionId);
  }

  const showEmpty = items.length === 0 && !live && !transcript.isLoading;
  // True first-run: no picked session AND the tenant has no conversations at
  // all yet → show the rich onboarding card set. Once they have history, the
  // empty new-chat screen falls back to the light one-line hint.
  const firstRun =
    showEmpty &&
    !sessionId &&
    sessions.isSuccess &&
    (sessions.data?.items.length ?? 0) === 0;

  return (
    <MobileShell>
      <div className="mx-auto flex min-h-screen w-full max-w-2xl flex-col">
        <TopBar
          title="Assistant"
          left={<BackButton href="/" label="Home" />}
          right={
            <div className="flex items-center gap-1">
              <a
                href="/assistant/usage"
                aria-label="Usage and budget"
                className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md text-accent active:opacity-60 no-tap-highlight"
              >
                <BarChart3 className="h-5 w-5" />
              </a>
              <a
                href="/assistant/channels"
                aria-label="Link channels"
                className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md text-accent active:opacity-60 no-tap-highlight"
              >
                <Link2 className="h-5 w-5" />
              </a>
              <a
                href="/assistant/builder"
                aria-label="Build agents"
                className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md text-accent active:opacity-60 no-tap-highlight"
              >
                <Wrench className="h-5 w-5" />
              </a>
              <button
                type="button"
                aria-label="New chat"
                onClick={() => resetTo(agentId, null)}
                className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md text-accent active:opacity-60 no-tap-highlight"
              >
                <Plus className="h-5 w-5" />
              </button>
              <button
                type="button"
                aria-label="Chat history"
                onClick={() => setSheetOpen(true)}
                className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md text-accent active:opacity-60 no-tap-highlight"
              >
                <History className="h-5 w-5" />
              </button>
            </div>
          }
        />

        {/* Agent picker */}
        <div className="sticky top-[calc(44px+env(safe-area-inset-top,0px))] z-20 bg-chrome px-4 py-2 backdrop-blur-md">
          <SegmentedControl
            ariaLabel="Agent"
            value={agentId}
            onChange={(next) => {
              if (next !== agentId) resetTo(next, null);
            }}
            options={agentOptions}
          />
        </div>

        {/* Messages */}
        <div className="flex-1 pb-[112px] pt-3">
          {agents.isError && (
            <SystemRow text="Couldn't reach the agent service. Pull to retry." />
          )}
          {transcript.isLoading && sessionId && (
            <SystemRow text="Loading conversation…" />
          )}
          {firstRun && <Onboarding personal={agentId !== "quill"} />}
          {showEmpty && !firstRun && (
            <div className="flex flex-col items-center gap-3 px-8 pt-16 text-center">
              <Sparkles className="h-8 w-8 text-label-tertiary" aria-hidden="true" />
              <p className="text-body text-label-secondary">
                {agentId === "quill"
                  ? "Ask about the Quill portfolio — finance, pipeline, operations, customers, approvals."
                  : "Your personal assistant. It remembers what matters across conversations."}
              </p>
            </div>
          )}

          {items.map((it, i) =>
            it.kind === "user" ? (
              <UserBubble key={i} text={it.text} time={it.created_at} />
            ) : it.kind === "system" ? (
              <SystemRow key={i} text={it.text} />
            ) : it.budget ? (
              <BudgetNotice key={i} text={it.text} />
            ) : (
              <AssistantBubble
                key={i}
                text={it.text}
                tools={it.tools}
                time={it.created_at}
              />
            ),
          )}

          {live && (
            <>
              <UserBubble text={live.user} />
              <AssistantBubble text={live.text} tools={live.chips} streaming />
            </>
          )}
          <div ref={scrollRef} />
        </div>
      </div>

      <AssistantInput
        disabled={!!live}
        busy={!!live}
        placeholder={`Message ${AGENT_LABELS[agentId] ?? agentId}…`}
        onSend={handleSend}
      />

      {/* Session history sheet */}
      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent side="right">
          <SheetHeader>
            <SheetTitle>Conversations</SheetTitle>
          </SheetHeader>
          <div className="mt-3 flex flex-col gap-1 overflow-y-auto">
            <button
              type="button"
              onClick={() => {
                resetTo(agentId, null);
                setSheetOpen(false);
              }}
              className="flex items-center gap-2 rounded-lg px-3 py-3 text-left text-body text-accent active:bg-bg-elevated no-tap-highlight"
            >
              <Plus className="h-4 w-4" /> New conversation
            </button>
            {(sessions.data?.items ?? []).map((s) => (
              <button
                key={s.session_id}
                type="button"
                onClick={() => {
                  resetTo(s.agent_id, s.session_id);
                  setSheetOpen(false);
                }}
                className={
                  "rounded-lg px-3 py-3 text-left active:bg-bg-elevated no-tap-highlight " +
                  (s.session_id === sessionId ? "bg-bg-elevated" : "")
                }
              >
                <p className="truncate text-body text-label-primary">
                  {s.preview || "New conversation"}
                </p>
                <p className="mt-0.5 text-caption-1 text-label-secondary">
                  {AGENT_LABELS[s.agent_id] ?? s.agent_id} ·{" "}
                  {new Date(s.updated_at).toLocaleString([], {
                    month: "short",
                    day: "numeric",
                    hour: "numeric",
                    minute: "2-digit",
                  })}
                </p>
              </button>
            ))}
            {sessions.data && sessions.data.items.length === 0 && (
              <p className="px-3 py-6 text-center text-footnote text-label-secondary">
                No conversations yet.
              </p>
            )}
          </div>
        </SheetContent>
      </Sheet>
    </MobileShell>
  );
}
