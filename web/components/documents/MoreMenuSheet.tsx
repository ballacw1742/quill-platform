"use client";

import * as React from "react";
import { Code2, ExternalLink, Link as LinkIcon, Printer } from "lucide-react";
import { toast } from "sonner";
import {
  BottomSheet,
  BottomSheetBody,
  BottomSheetTopBar,
} from "@/components/ui/sheet";
import type { Document } from "@/lib/schemas";

/**
 * MoreMenuSheet — Phase E commit 4.
 *
 * Bottom sheet behind the "•••" button on /documents/[id]. iOS Action
 * Sheet pattern: full-width tappable rows on a single sheet, no nesting.
 *
 * Picked for a real PM workflow:
 *   1. View raw JSON      — for engineers / debugging via long-press
 *   2. Copy link          — share-link without invoking native share
 *   3. Open in new tab    — desktop / tablet companion
 *   4. Print              — paper trail for owner / partner reviews
 *
 * Each item closes the sheet on tap; no chained sheets to keep the menu
 * single-purpose and predictable.
 */

export function MoreMenuSheet({
  open,
  onOpenChange,
  doc,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  doc: Document | null;
}) {
  const [jsonOpen, setJsonOpen] = React.useState(false);

  const docUrl = React.useMemo(() => {
    if (!doc || typeof window === "undefined") return null;
    return `${window.location.origin}/documents/${encodeURIComponent(doc.id)}`;
  }, [doc]);

  const handleCopyLink = async () => {
    if (!docUrl) return;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(docUrl);
        toast.success("Link copied");
      } else {
        toast.error("Couldn't copy. Long-press the URL bar instead.");
      }
    } catch {
      toast.error("Couldn't copy. Long-press the URL bar instead.");
    } finally {
      onOpenChange(false);
    }
  };

  const handleOpenInNewTab = () => {
    if (!docUrl) return;
    window.open(docUrl, "_blank", "noopener,noreferrer");
    onOpenChange(false);
  };

  const handlePrint = () => {
    onOpenChange(false);
    // Wait one tick so the sheet animates out before the print dialog grabs
    // focus (otherwise iOS Safari prints the sheet still half-on-screen).
    setTimeout(() => {
      if (typeof window !== "undefined") window.print();
    }, 300);
  };

  const handleViewJson = () => {
    onOpenChange(false);
    // Short delay so the sheets don't fight for the dialog stack on iOS.
    setTimeout(() => setJsonOpen(true), 200);
  };

  return (
    <>
      <BottomSheet
        open={open}
        onOpenChange={onOpenChange}
        ariaLabel="More options"
      >
        <BottomSheetTopBar
          title="More options"
          right={
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              className="text-body text-accent active:opacity-60 no-tap-highlight min-h-[44px] -mr-2 px-2"
            >
              Done
            </button>
          }
        />
        <BottomSheetBody>
          <ul className="flex flex-col -mx-4">
            <MenuItem
              icon={<LinkIcon className="h-5 w-5" />}
              label="Copy link"
              onClick={handleCopyLink}
              disabled={!docUrl}
            />
            <MenuItem
              icon={<ExternalLink className="h-5 w-5" />}
              label="Open in new tab"
              onClick={handleOpenInNewTab}
              disabled={!docUrl}
            />
            <MenuItem
              icon={<Printer className="h-5 w-5" />}
              label="Print"
              onClick={handlePrint}
              disabled={!doc}
            />
            <MenuItem
              icon={<Code2 className="h-5 w-5" />}
              label="View raw JSON"
              onClick={handleViewJson}
              disabled={!doc}
              divider={false}
            />
          </ul>
        </BottomSheetBody>
      </BottomSheet>

      {/* Raw JSON viewer — separate sheet, opened from the menu. */}
      <BottomSheet
        open={jsonOpen}
        onOpenChange={setJsonOpen}
        ariaLabel="Raw document JSON"
        fullHeight
      >
        <BottomSheetTopBar
          title="Raw JSON"
          left={
            <button
              type="button"
              onClick={() => setJsonOpen(false)}
              className="text-body text-accent active:opacity-60 no-tap-highlight min-h-[44px] -ml-2 px-2"
            >
              Done
            </button>
          }
          right={
            doc && (
              <button
                type="button"
                onClick={async () => {
                  if (!doc) return;
                  try {
                    if (navigator.clipboard?.writeText) {
                      await navigator.clipboard.writeText(
                        JSON.stringify(doc, null, 2),
                      );
                      toast.success("JSON copied");
                    } else {
                      toast.error("Couldn't copy. Select text manually.");
                    }
                  } catch {
                    toast.error("Couldn't copy. Select text manually.");
                  }
                }}
                className="text-body text-accent active:opacity-60 no-tap-highlight min-h-[44px] -mr-2 px-2"
              >
                Copy
              </button>
            )
          }
        />
        <BottomSheetBody>
          {doc ? (
            <pre className="text-footnote text-label-primary font-mono whitespace-pre-wrap break-words bg-bg-elevated rounded-md p-3 overflow-x-auto">
              {JSON.stringify(doc, null, 2)}
            </pre>
          ) : (
            <p className="text-callout text-label-secondary">
              Nothing to show.
            </p>
          )}
        </BottomSheetBody>
      </BottomSheet>
    </>
  );
}

function MenuItem({
  icon,
  label,
  onClick,
  disabled,
  divider = true,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  divider?: boolean;
}) {
  return (
    <li className={divider ? "border-b border-separator/40" : undefined}>
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        className="flex w-full items-center gap-3 px-4 py-3.5 min-h-[56px] no-tap-highlight active:bg-bg-elevated/60 disabled:opacity-40 disabled:active:bg-transparent"
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center text-accent">
          {icon}
        </span>
        <span className="flex-1 text-headline text-label-primary text-left">
          {label}
        </span>
      </button>
    </li>
  );
}
