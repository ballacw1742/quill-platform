"use client";

import * as React from "react";
import { CheckCircle, XCircle, Loader2, GitCommit } from "lucide-react";
import { cn } from "@/lib/utils";
import type { DevChatMessage } from "@/lib/schemas";

/**
 * DevChatMessage — renders a single message bubble.
 *
 * Layout:
 *   user   → right-aligned, accent background
 *   agent  → left-aligned, surface background
 *   system → center-aligned, grey muted
 */
export function DevChatMessageBubble({ message }: { message: DevChatMessage }) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";

  if (isSystem) {
    return (
      <div className="flex justify-center my-2">
        <span className="text-caption-1 text-label-secondary bg-bg-elevated rounded-full px-3 py-1">
          {message.content}
        </span>
      </div>
    );
  }

  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start", "mb-3 px-4")}>
      <div
        className={cn(
          "max-w-[80%] rounded-2xl px-4 py-3 min-w-[44px]",
          isUser
            ? "bg-accent text-white rounded-br-sm"
            : "bg-bg-elevated text-label-primary rounded-bl-sm",
        )}
      >
        {/* Streaming state */}
        {message.status === "queued" || message.status === "streaming" ? (
          <div className="flex items-center gap-2 text-body">
            <Loader2 className="h-4 w-4 animate-spin shrink-0" />
            <span>{message.content || "Axe is working…"}</span>
          </div>
        ) : message.status === "completed" && !isUser ? (
          <AgentCompletedContent message={message} />
        ) : message.status === "failed" ? (
          <AgentFailedContent message={message} />
        ) : message.status === "cancelled" ? (
          <span className="text-body text-label-secondary italic">Cancelled.</span>
        ) : (
          <p className="text-body whitespace-pre-wrap break-words">{message.content}</p>
        )}

        {/* Timestamp */}
        <div
          className={cn(
            "mt-1 text-caption-2 text-right",
            isUser ? "text-white/70" : "text-label-tertiary",
          )}
        >
          {new Date(message.created_at).toLocaleTimeString([], {
            hour: "numeric",
            minute: "2-digit",
          })}
        </div>
      </div>
    </div>
  );
}

function AgentCompletedContent({ message }: { message: DevChatMessage }) {
  const sha = message.commit_sha;
  const files = message.files_changed ?? [];
  const cost = message.cost_usd;

  return (
    <div className="space-y-2">
      {message.content && (
        <p className="text-body whitespace-pre-wrap break-words">{message.content}</p>
      )}
      {sha && (
        <div className="flex items-center gap-1.5 text-caption-1 text-label-secondary">
          <GitCommit className="h-3.5 w-3.5 shrink-0" />
          <a
            href={`https://github.com/charlesmitchell/quill-platform/commit/${sha}`}
            target="_blank"
            rel="noopener noreferrer"
            className="font-mono text-accent underline truncate"
            aria-label={`View commit ${sha.slice(0, 7)}`}
          >
            {sha.slice(0, 7)}
          </a>
        </div>
      )}
      {files.length > 0 && (
        <div className="text-caption-1 text-label-secondary">
          <span className="font-medium">{files.length} file{files.length !== 1 ? "s" : ""} changed</span>
          <ul className="mt-1 list-disc list-inside space-y-0.5">
            {files.slice(0, 5).map((f) => (
              <li key={f} className="truncate">{f}</li>
            ))}
            {files.length > 5 && <li className="text-label-tertiary">+{files.length - 5} more</li>}
          </ul>
        </div>
      )}
      {cost != null && cost > 0 && (
        <div className="text-caption-2 text-label-tertiary">${cost.toFixed(4)}</div>
      )}
      <div className="flex items-center gap-1 text-caption-1 text-green-600 dark:text-green-400">
        <CheckCircle className="h-3.5 w-3.5" />
        <span>Done</span>
      </div>
    </div>
  );
}

function AgentFailedContent({ message }: { message: DevChatMessage }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 text-danger">
        <XCircle className="h-4 w-4 shrink-0" />
        <span className="text-body font-medium">Failed</span>
      </div>
      {message.content && (
        <p className="text-caption-1 text-danger/80 whitespace-pre-wrap">{message.content}</p>
      )}
    </div>
  );
}
