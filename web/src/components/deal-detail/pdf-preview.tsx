"use client";

import * as React from "react";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ChevronLeft, ChevronRight, Download, ExternalLink, Eye, Table } from "lucide-react";
import type { DealDocument } from "@/lib/types";

/** Preview PDF pages in browsers without a built-in PDF viewer. */
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
              <a href={url} target="_blank" rel="noreferrer" title="Open in new tab" aria-label="Open original in new tab">
                <ExternalLink className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Open</span>
              </a>
            </Button>
            <Button size="sm" variant="ghost" asChild>
              <a href={url} download={doc.filename} title="Download" aria-label="Download">
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
          open && <PdfPages key={doc.id} doc={doc} />
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

function PdfPages({ doc }: { doc: DealDocument }) {
  const [page, setPage] = React.useState(1);
  const pages = Math.max(1, doc.page_count);
  return (
    <>
      <div className="flex shrink-0 items-center justify-center gap-3 border-b border-border/70 px-3 py-2">
        <Button size="sm" variant="outline" aria-label="Previous page" disabled={page === 1} onClick={() => setPage(current => Math.max(1, current - 1))}>
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span aria-live="polite" className="text-sm tabular-nums">Page {page} of {pages}</span>
        <Button size="sm" variant="outline" aria-label="Next page" disabled={page >= pages} onClick={() => setPage(current => Math.min(pages, current + 1))}>
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
      <PdfPageImage key={page} docId={doc.id} page={page} />
    </>
  );
}

function PdfPageImage({ docId, page }: { docId: number; page: number }) {
  const [status, setStatus] = React.useState<"loading" | "ready" | "failed">("loading");
  return (
    <div className="min-h-0 flex-1 overflow-auto bg-muted/60 p-2 sm:p-4">
      {status === "loading" && <p role="status" className="p-4 text-center text-sm text-muted-foreground">Loading page…</p>}
      {status === "failed" ? (
        <p role="alert" className="p-4 text-center text-sm">This page couldn’t be previewed. Open or download the original above.</p>
      ) : (
        // The same-origin API renders and authenticates each private page.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={`/api/deals/documents/${docId}/preview/${page}`}
          alt={`PDF page ${page}`}
          className={status === "ready" ? "mx-auto block h-auto max-w-full bg-white shadow" : "invisible"}
          onLoad={(event) => {
            if (event.currentTarget.parentElement) event.currentTarget.parentElement.scrollTop = 0;
            setStatus("ready");
          }}
          onError={() => setStatus("failed")}
        />
      )}
    </div>
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
