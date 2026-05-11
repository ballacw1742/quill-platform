"use client";

import * as React from "react";
import { Send, X, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * DevChatInput — the sticky input bar at the bottom of the chat view.
 *
 * States:
 *   idle        — input enabled, placeholder "Tell Axe what to change…"
 *   in_progress — input disabled, banner shows "Axe is working… [Cancel]"
 *   submitting  — spinner on send button
 */
export function DevChatInput({
  state,
  currentTaskId,
  onSend,
  onCancel,
  isSubmitting,
}: {
  state: "idle" | "in_progress";
  currentTaskId?: string | null;
  onSend: (content: string) => void;
  onCancel: (taskId: string) => void;
  isSubmitting?: boolean;
}) {
  const [value, setValue] = React.useState("");
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  const isLocked = state === "in_progress";

  function handleSend() {
    const trimmed = value.trim();
    if (!trimmed || isLocked || isSubmitting) return;
    onSend(trimmed);
    setValue("");
    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setValue(e.target.value);
    // Auto-grow textarea (max ~5 lines)
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }

  return (
    <div className="border-t border-separator/40 bg-chrome pb-safe">
      {/* In-progress banner */}
      {isLocked && (
        <div className="flex items-center justify-between px-4 py-2 bg-fill-secondary">
          <div className="flex items-center gap-2 text-body text-label-secondary">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>Axe is working…</span>
          </div>
          {currentTaskId && (
            <button
              type="button"
              onClick={() => onCancel(currentTaskId)}
              className="flex items-center gap-1 text-danger text-subhead font-medium min-h-[44px] min-w-[44px] px-2 rounded-md active:opacity-60"
            >
              <X className="h-4 w-4" />
              Cancel
            </button>
          )}
        </div>
      )}

      {/* Input row */}
      <div className="flex items-end gap-2 px-4 py-3">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          disabled={isLocked}
          rows={1}
          placeholder={isLocked ? "" : "Tell Axe what to change…"}
          className={cn(
            "flex-1 resize-none rounded-2xl border border-separator bg-fill-secondary px-4 py-2.5",
            "text-body text-label-primary placeholder:text-label-tertiary",
            "focus:outline-none focus:ring-2 focus:ring-accent/50",
            "min-h-[44px] max-h-[120px] overflow-y-auto",
            "transition-opacity",
            isLocked && "opacity-40 cursor-not-allowed",
          )}
          aria-label="Message to Axe"
        />
        <button
          type="button"
          onClick={handleSend}
          disabled={isLocked || !value.trim() || isSubmitting}
          className={cn(
            "flex h-[44px] w-[44px] shrink-0 items-center justify-center rounded-full",
            "bg-accent text-white transition-all active:scale-95",
            "disabled:opacity-40 disabled:cursor-not-allowed",
          )}
          aria-label="Send message"
        >
          {isSubmitting ? (
            <Loader2 className="h-5 w-5 animate-spin" />
          ) : (
            <Send className="h-5 w-5" />
          )}
        </button>
      </div>
    </div>
  );
}
