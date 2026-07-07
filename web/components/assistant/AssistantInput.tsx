"use client";

import * as React from "react";
import { Loader2, Send } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * AssistantInput — sticky composer for the /assistant chat (Sprint A5).
 * Mirrors DevChatInput's auto-growing textarea, pinned to the bottom edge
 * (the iOS-redesign shell has no tab bar).
 */
export function AssistantInput({
  disabled,
  busy,
  placeholder = "Message your agent…",
  onSend,
}: {
  /** Composer locked (e.g. while a turn is streaming). */
  disabled?: boolean;
  /** Show the spinner on the send button. */
  busy?: boolean;
  placeholder?: string;
  onSend: (text: string) => void;
}) {
  const [value, setValue] = React.useState("");
  const ref = React.useRef<HTMLTextAreaElement>(null);

  function send() {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
    if (ref.current) ref.current.style.height = "auto";
  }

  return (
    <div className="fixed bottom-0 left-0 right-0 z-30 border-t border-separator/40 bg-chrome pb-safe backdrop-blur-md">
      <div className="mx-auto flex max-w-2xl items-end gap-2 px-4 py-3">
        <textarea
          ref={ref}
          value={value}
          rows={1}
          disabled={disabled}
          placeholder={placeholder}
          onChange={(e) => {
            setValue(e.target.value);
            const el = e.target;
            el.style.height = "auto";
            el.style.height = Math.min(el.scrollHeight, 120) + "px";
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          className={cn(
            "flex-1 resize-none rounded-2xl border border-separator bg-bg-elevated px-4 py-2.5",
            "text-body text-label-primary placeholder:text-label-tertiary",
            "focus:outline-none focus:ring-2 focus:ring-accent/50",
            "min-h-[44px] max-h-[120px] overflow-y-auto transition-opacity",
            disabled && "opacity-40",
          )}
          aria-label="Message your agent"
        />
        <button
          type="button"
          onClick={send}
          disabled={disabled || !value.trim()}
          aria-label="Send message"
          className={cn(
            "flex h-[44px] w-[44px] shrink-0 items-center justify-center rounded-full",
            "bg-accent text-white transition-all active:scale-95",
            "disabled:cursor-not-allowed disabled:opacity-40",
          )}
        >
          {busy ? (
            <Loader2 className="h-5 w-5 animate-spin" />
          ) : (
            <Send className="h-5 w-5" />
          )}
        </button>
      </div>
    </div>
  );
}
