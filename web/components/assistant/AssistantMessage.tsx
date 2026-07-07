"use client";

import * as React from "react";
import { Check, Loader2, ShieldX, Wrench, PiggyBank } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Assistant chat bubbles — Sprint A5 (agent-cloud/WEBCHAT.md §3.3/§3.4).
 *
 * Follows the dev-chat bubble conventions: user right/accent, agent
 * left/elevated, system rows centered + muted. Tool activity renders as
 * chips; a budget-exceeded turn renders as a distinct notice, not an error.
 */

export type ToolChip = { name: string; status: "start" | "ok" | "denied" };

export function UserBubble({ text, time }: { text: string; time?: string }) {
  return (
    <div className="mb-3 flex justify-end px-4">
      <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-accent px-4 py-3 text-white">
        <p className="text-body whitespace-pre-wrap break-words">{text}</p>
        {time && <BubbleTime time={time} light />}
      </div>
    </div>
  );
}

export function AssistantBubble({
  text,
  tools = [],
  streaming = false,
  time,
}: {
  text: string;
  tools?: ToolChip[];
  streaming?: boolean;
  time?: string;
}) {
  return (
    <div className="mb-3 flex justify-start px-4">
      <div className="max-w-[80%] rounded-2xl rounded-bl-sm bg-bg-elevated px-4 py-3 text-label-primary">
        {tools.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {tools.map((t, i) => (
              <ToolChipPill key={`${t.name}-${i}`} chip={t} />
            ))}
          </div>
        )}
        {text ? (
          <p className="text-body whitespace-pre-wrap break-words">{text}</p>
        ) : streaming ? (
          <div className="flex items-center gap-2 text-body text-label-secondary">
            <Loader2 className="h-4 w-4 animate-spin shrink-0" />
            <span>Thinking…</span>
          </div>
        ) : null}
        {streaming && text && (
          <span
            className="ml-0.5 inline-block h-4 w-[2px] animate-pulse bg-label-secondary align-text-bottom"
            aria-hidden="true"
          />
        )}
        {!streaming && time && <BubbleTime time={time} />}
      </div>
    </div>
  );
}

export function SystemRow({ text }: { text: string }) {
  return (
    <div className="my-2 flex justify-center px-4">
      <span className="max-w-[90%] truncate rounded-full bg-bg-elevated px-3 py-1 text-caption-1 text-label-secondary">
        {text}
      </span>
    </div>
  );
}

/** Budget cap notice — a first-class state, never styled as an error. */
export function BudgetNotice({ text }: { text?: string }) {
  return (
    <div className="mb-3 flex justify-start px-4">
      <div className="max-w-[85%] rounded-2xl border border-warning/40 bg-warning/10 px-4 py-3">
        <div className="flex items-center gap-2 text-subhead font-medium text-label-primary">
          <PiggyBank className="h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
          Monthly budget reached
        </div>
        <p className="mt-1 text-footnote text-label-secondary whitespace-pre-wrap break-words">
          {text ||
            "This agent hit its monthly usage cap, so it politely declined the turn. It resets at the start of next month."}
        </p>
      </div>
    </div>
  );
}

function ToolChipPill({ chip }: { chip: ToolChip }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-caption-1",
        chip.status === "denied"
          ? "bg-danger/10 text-danger"
          : "bg-bg-tertiary text-label-secondary",
      )}
    >
      {chip.status === "start" ? (
        <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
      ) : chip.status === "denied" ? (
        <ShieldX className="h-3 w-3" aria-hidden="true" />
      ) : (
        <Check className="h-3 w-3 text-success" aria-hidden="true" />
      )}
      <Wrench className="h-3 w-3" aria-hidden="true" />
      <span className="font-mono">{chip.name}</span>
    </span>
  );
}

function BubbleTime({ time, light = false }: { time: string; light?: boolean }) {
  const iso = /[Zz]|[+-]\d{2}:\d{2}$/.test(time) ? time : time + "Z";
  return (
    <div
      className={cn(
        "mt-1 text-caption-2 text-right",
        light ? "text-white/70" : "text-label-tertiary",
      )}
    >
      {new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
    </div>
  );
}
