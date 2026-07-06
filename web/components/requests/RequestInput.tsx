"use client";

import * as React from "react";
import { Send, Paperclip, Link as LinkIcon, X, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * RequestInput — the fixed bottom input bar for the Requests page.
 *
 * Features:
 *   - Text input with auto-grow
 *   - Paperclip → file picker (PDF, DOCX, multiple)
 *   - Drive link icon → inline URL input (toggleable)
 *   - Send button (disabled while processing)
 *   - File name chips above the input
 *   - Example prompt chips (scrollable horizontal row, controlled by parent)
 *   - prefillValue prop: when set, pre-populates the text input (e.g. quick
 *     actions from the empty state or agent chip taps)
 */

export interface RequestInputValue {
  message: string;
  files: File[];
  driveUrl: string;
}

interface RequestInputProps {
  onSend: (value: RequestInputValue) => void;
  isProcessing?: boolean;
  /** Chips shown above the textarea. Changes based on selected agent. */
  examples?: string[];
  /** When set, pre-populates the textarea. Parent clears after use. */
  prefillValue?: string | null;
  /** Called after prefillValue has been consumed (so parent can reset it). */
  onPrefillConsumed?: () => void;
}

export function RequestInput({
  onSend,
  isProcessing,
  examples = [],
  prefillValue,
  onPrefillConsumed,
}: RequestInputProps) {
  const [message, setMessage] = React.useState("");
  const [files, setFiles] = React.useState<File[]>([]);
  const [driveUrl, setDriveUrl] = React.useState("");
  const [driveOpen, setDriveOpen] = React.useState(false);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  // Apply prefillValue whenever it changes
  React.useEffect(() => {
    if (prefillValue) {
      setMessage(prefillValue);
      // Auto-resize
      if (textareaRef.current) {
        textareaRef.current.style.height = "auto";
        textareaRef.current.style.height =
          Math.min(textareaRef.current.scrollHeight, 120) + "px";
        textareaRef.current.focus();
      }
      onPrefillConsumed?.();
    }
  }, [prefillValue]); // eslint-disable-line react-hooks/exhaustive-deps

  const canSend =
    (message.trim().length > 0 || files.length > 0 || driveUrl.trim().length > 0) &&
    !isProcessing;

  function handleSend() {
    if (!canSend) return;
    onSend({ message: message.trim(), files, driveUrl: driveUrl.trim() });
    setMessage("");
    setFiles([]);
    setDriveUrl("");
    setDriveOpen(false);
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

  function handleTextChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setMessage(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(e.target.files ?? []);
    setFiles((prev) => [...prev, ...selected]);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function removeFile(idx: number) {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  }

  function handleExampleChip(text: string) {
    setMessage(text);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height =
        Math.min(textareaRef.current.scrollHeight, 120) + "px";
      textareaRef.current.focus();
    }
  }

  return (
    <div
      className={cn(
        "fixed left-0 right-0 z-30",
        "border-t border-separator/40 bg-chrome backdrop-blur-md",
        "bottom-[calc(env(safe-area-inset-bottom,0px)+72px)]",
      )}
    >
      {/* File chips */}
      {files.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-4 pt-2 pb-0">
          {files.map((file, i) => (
            <span
              key={`${file.name}-${i}`}
              className="inline-flex items-center gap-1 rounded-full bg-accent/10 px-2 py-0.5 text-caption-2 text-accent"
            >
              <Paperclip className="h-3 w-3" aria-hidden />
              <span className="max-w-[120px] truncate">{file.name}</span>
              <button
                type="button"
                onClick={() => removeFile(i)}
                className="ml-0.5 rounded-full hover:bg-accent/20 p-0.5"
                aria-label={`Remove ${file.name}`}
              >
                <X className="h-2.5 w-2.5" />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Drive URL input (toggleable) */}
      {driveOpen && (
        <div className="flex items-center gap-2 px-4 pt-2">
          <LinkIcon className="h-4 w-4 text-label-tertiary shrink-0" aria-hidden />
          <input
            type="url"
            value={driveUrl}
            onChange={(e) => setDriveUrl(e.target.value)}
            placeholder="Paste Google Drive link…"
            className={cn(
              "flex-1 rounded-xl border border-separator bg-bg-elevated px-3 py-2",
              "text-body text-label-primary placeholder:text-label-tertiary",
              "focus:outline-none focus:ring-2 focus:ring-accent/50",
              "min-h-[36px]",
            )}
            aria-label="Google Drive link"
          />
          <button
            type="button"
            onClick={() => { setDriveUrl(""); setDriveOpen(false); }}
            className="rounded-full p-1 text-label-secondary hover:bg-bg-elevated"
            aria-label="Close Drive link input"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Example prompt chips — scrollable horizontal row */}
      {examples.length > 0 && (
        <div
          className="flex gap-2 px-4 pt-2 pb-0 overflow-x-auto scrollbar-none"
          aria-label="Example prompts"
          style={{ WebkitOverflowScrolling: "touch" }}
        >
          {examples.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => handleExampleChip(example)}
              disabled={isProcessing}
              className={cn(
                "shrink-0 rounded-full border border-separator bg-bg-elevated",
                "px-3 py-1.5 text-caption-1 text-label-secondary whitespace-nowrap",
                "transition-colors hover:bg-bg-secondary hover:text-label-primary",
                "active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed",
              )}
            >
              {example}
            </button>
          ))}
        </div>
      )}

      {/* Input row */}
      <div className="flex items-end gap-2 px-4 py-3">
        {/* File picker button */}
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={isProcessing}
          className={cn(
            "flex h-[44px] w-[44px] shrink-0 items-center justify-center rounded-full",
            "bg-bg-elevated text-label-secondary",
            "active:opacity-70 disabled:opacity-40 disabled:cursor-not-allowed",
          )}
          aria-label="Attach file"
        >
          <Paperclip className="h-5 w-5" aria-hidden />
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.doc,.xlsx,.xls,.csv,.txt"
          onChange={handleFileChange}
          className="hidden"
          aria-hidden
        />

        {/* Drive link button */}
        <button
          type="button"
          onClick={() => setDriveOpen((o) => !o)}
          disabled={isProcessing}
          className={cn(
            "flex h-[44px] w-[44px] shrink-0 items-center justify-center rounded-full",
            "bg-bg-elevated text-label-secondary",
            "active:opacity-70 disabled:opacity-40 disabled:cursor-not-allowed",
            driveOpen && "text-accent bg-accent/10",
          )}
          aria-label="Add Google Drive link"
          aria-pressed={driveOpen}
        >
          <LinkIcon className="h-5 w-5" aria-hidden />
        </button>

        {/* Text input */}
        <textarea
          ref={textareaRef}
          value={message}
          onChange={handleTextChange}
          onKeyDown={handleKeyDown}
          disabled={isProcessing}
          rows={1}
          placeholder={isProcessing ? "Processing…" : "Type a request…"}
          className={cn(
            "flex-1 resize-none rounded-2xl border border-separator bg-bg-elevated px-4 py-2.5",
            "text-body text-label-primary placeholder:text-label-tertiary",
            "focus:outline-none focus:ring-2 focus:ring-accent/50",
            "min-h-[44px] max-h-[120px] overflow-y-auto",
            "transition-opacity",
            isProcessing && "opacity-40 cursor-not-allowed",
          )}
          aria-label="Describe your request"
        />

        {/* Send button */}
        <button
          type="button"
          onClick={handleSend}
          disabled={!canSend}
          className={cn(
            "flex h-[44px] w-[44px] shrink-0 items-center justify-center rounded-full",
            "bg-accent text-white transition-all active:scale-95",
            "disabled:opacity-40 disabled:cursor-not-allowed",
          )}
          aria-label="Send request"
        >
          {isProcessing ? (
            <Loader2 className="h-5 w-5 animate-spin" />
          ) : (
            <Send className="h-5 w-5" />
          )}
        </button>
      </div>
    </div>
  );
}
