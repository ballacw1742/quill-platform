"use client";

import * as React from "react";
import {
  FileCode,
  FileText,
  FileType,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";
import {
  BottomSheet,
  BottomSheetTopBar,
  BottomSheetBody,
} from "@/components/ui/sheet";
import { ListRow } from "@/components/ui/list-row";
import { useDocumentExport } from "@/lib/api";
import type { DocumentExportFormat } from "@/lib/schemas";

/**
 * ExportSheet — bottom sheet with the three export formats from
 * DOCUMENTS_SPEC \u00a7"Document detail screen / Bottom action bar".
 *
 *   \u2022 Markdown \u2192 .md
 *   \u2022 PDF      \u2192 .pdf
 *   \u2022 Word     \u2192 .docx
 *
 * Tapping a row triggers a real browser download via useDocumentExport,
 * shows a toast, and closes the sheet. While the download is in flight we
 * disable the row and show a small spinner so a slow PDF doesn't look stuck.
 */
export function ExportSheet({
  documentId,
  open,
  onOpenChange,
}: {
  documentId: string | null;
  open: boolean;
  onOpenChange: (next: boolean) => void;
}) {
  return (
    <BottomSheet
      open={open}
      onOpenChange={onOpenChange}
      ariaLabel="Export document"
    >
      <BottomSheetTopBar
        title="Export"
        right={
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="text-accent text-body active:opacity-60 no-tap-highlight"
          >
            Done
          </button>
        }
      />
      <BottomSheetBody className="pb-safe">
        <ul className="overflow-hidden rounded-lg bg-bg-tertiary">
          <ExportRow
            documentId={documentId}
            format="md"
            icon={<FileCode className="h-4 w-4" />}
            label="Markdown"
            subtitle="Plain text with formatting; opens in any editor"
            onDone={() => onOpenChange(false)}
          />
          <ExportRow
            documentId={documentId}
            format="pdf"
            icon={<FileText className="h-4 w-4" />}
            label="PDF"
            subtitle="Best for printing or sharing as-is"
            onDone={() => onOpenChange(false)}
          />
          <ExportRow
            documentId={documentId}
            format="docx"
            icon={<FileType className="h-4 w-4" />}
            label="Word"
            subtitle="Editable in Microsoft Word or Google Docs"
            onDone={() => onOpenChange(false)}
            hideDivider
          />
        </ul>
      </BottomSheetBody>
    </BottomSheet>
  );
}

function ExportRow({
  documentId,
  format,
  icon,
  label,
  subtitle,
  onDone,
  hideDivider,
}: {
  documentId: string | null;
  format: DocumentExportFormat;
  icon: React.ReactNode;
  label: string;
  subtitle: string;
  onDone: () => void;
  hideDivider?: boolean;
}) {
  const [busy, setBusy] = React.useState(false);
  const triggerExport = useDocumentExport(documentId, format);

  const handleClick = async () => {
    if (!documentId || busy) return;
    setBusy(true);
    try {
      await triggerExport();
      toast.success(`Downloaded ${label.toLowerCase()}`);
      onDone();
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error("export failed", e);
      toast.error(`Couldn't export ${label.toLowerCase()}. Try again.`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <ListRow
      icon={busy ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      iconTone="accent"
      title={label}
      subtitle={subtitle}
      onClick={handleClick}
      hideDivider={hideDivider}
      ariaLabel={`Export as ${label}`}
    />
  );
}
