"use client";

import * as React from "react";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Download, ExternalLink, Eye, Table } from "lucide-react";
import type { DealDocument } from "@/lib/types";

/**
 * Inline PDF viewer modal. Uses the browser's native PDF rendering
 * (via `<iframe>`), which means no extra client bundle weight (pdf.js
 * is several hundred KB) and works on every evergreen browser +
 * mobile Safari. Spreadsheets are shown as extracted/downloadable files
 * because browsers do not render XLSX inline reliably.
 */
export function PdfPreviewDialog({
  doc,
  open,
  onOpenChange,
}: {
  doc: DealDocument | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  if (!doc) return null;
  const url = `/api/deals/documents/${doc.id}/file`;
  const isPdf = doc.filename.toLowerCase().endsWith(".pdf");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        hideClose
        className="max-w-5xl w-[96vw] h-[88vh] p-0 overflow-hidden flex flex-col"
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-border/70 shrink-0">
          <div className="min-w-0">
            <DialogTitle className="truncate">{doc.filename}</DialogTitle>
            <DialogDescription className="text-[11px] mt-0.5">
              {doc.page_count} {docUnit(doc.filename, doc.page_count)}
              {" · "}
              {doc.doc_type.replace(/_/g, " ")}
            </DialogDescription>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Button size="sm" variant="ghost" asChild>
              <a href={url} target="_blank" rel="noreferrer" title="Open in new tab">
                <ExternalLink className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Open</span>
              </a>
            </Button>
            <Button size="sm" variant="ghost" asChild>
              <a href={url} download={doc.filename} title="Download">
                <Download className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Download</span>
              </a>
            </Button>
            <Button size="sm" variant="outline" onClick={() => onOpenChange(false)}>
              Close
            </Button>
          </div>
        </div>

        {isPdf ? (
          <div className="flex-1 bg-black/30 min-h-0">
            {/* Browser-native PDF viewer. `#toolbar=1` shows Chrome's
                page nav + download; other browsers ignore unknown hashes. */}
            <iframe
              src={`${url}#toolbar=1&view=FitH`}
              title={doc.filename}
              className="w-full h-full border-0"
            />
            <div className="sr-only">
              <a href={url}>Open {doc.filename}</a>
            </div>
          </div>
        ) : (
          <div className="flex-1 min-h-0 grid place-items-center bg-muted/20 p-8 text-center">
            <div>
              <div className="mx-auto grid h-12 w-12 place-items-center rounded-lg bg-primary/10 text-primary ring-1 ring-primary/25">
                <Table className="h-5 w-5" />
              </div>
              <div className="mt-4 text-sm font-medium">Spreadsheet extracted</div>
              <p className="mt-1 max-w-sm text-xs leading-5 text-muted-foreground">
                The workbook has been converted into sheet text for analysis. Use Open or Download to inspect the original file.
              </p>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

/**
 * "Preview" button used inside the Documents tab row. Hover-reveals
 * on desktop; tap-to-activate on touch.
 */
export function PreviewButton({
  doc,
  onOpen,
}: {
  doc: DealDocument;
  onOpen: (d: DealDocument) => void;
}) {
  return (
    <button
      onClick={(e) => {
        e.preventDefault();
        onOpen(doc);
      }}
      title={`Preview ${doc.filename}`}
      className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
    >
      <Eye className="h-3.5 w-3.5" />
    </button>
  );
}

function docUnit(filename: string, count: number): string {
  const lower = filename.toLowerCase();
  const singular = lower.endsWith(".xlsx") || lower.endsWith(".xlsm") || lower.endsWith(".xls") || lower.endsWith(".csv") ? "sheet" : "page";
  return count === 1 ? singular : `${singular}s`;
}
