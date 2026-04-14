"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  Upload,
  FileText,
  Trash2,
  Loader2,
  FileUp,
  CheckCircle2,
  Image as ImageIcon,
  Table as TableIcon,
  ScanText,
} from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { DealDocument } from "@/lib/types";

type Upload = {
  id: string;
  filename: string;
  status: "uploading" | "extracting" | "done" | "error";
  progress: number;
  ocr_pages?: number;
  tables?: number;
  images?: number;
  error?: string;
};

const DOC_TYPES: Array<{ key: string; label: string }> = [
  { key: "offering_memo", label: "Offering Memo" },
  { key: "proforma", label: "Proforma" },
  { key: "market_study", label: "Market Study" },
  { key: "other", label: "Other" },
];

export function DocumentsPanel({
  dealId,
  documents,
}: {
  dealId: number;
  documents: DealDocument[];
}) {
  const router = useRouter();
  const [dragActive, setDragActive] = React.useState(false);
  const [docType, setDocType] = React.useState<string>("offering_memo");
  const [uploads, setUploads] = React.useState<Upload[]>([]);
  const inputRef = React.useRef<HTMLInputElement>(null);

  async function handleFiles(files: FileList | File[]) {
    const list = Array.from(files);
    for (const file of list) {
      const localId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      setUploads((prev) => [...prev, { id: localId, filename: file.name, status: "uploading", progress: 0 }]);

      try {
        await uploadWithProgress(file, dealId, docType, (p) => {
          setUploads((prev) => prev.map((u) => (u.id === localId ? { ...u, progress: p } : u)));
        }).then((result) => {
          setUploads((prev) =>
            prev.map((u) =>
              u.id === localId
                ? {
                    ...u,
                    status: "done",
                    progress: 100,
                    ocr_pages: result.extraction?.ocr_pages ?? 0,
                    tables: result.extraction?.tables ?? 0,
                    images: result.extraction?.images ?? 0,
                  }
                : u,
            ),
          );
          toast.success("Document uploaded", { description: file.name });
          router.refresh();
        });
      } catch (e) {
        const msg = (e as Error)?.message || "Upload failed";
        setUploads((prev) => prev.map((u) => (u.id === localId ? { ...u, status: "error", error: msg } : u)));
        toast.error("Upload failed", { description: file.name });
      }
    }
  }

  async function deleteDoc(docId: number, name: string) {
    try {
      const res = await fetch(`/api/deals/documents/${docId}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      toast.success("Deleted", { description: name });
      router.refresh();
    } catch (e) {
      toast.error("Couldn't delete", { description: (e as Error).message });
    }
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-6">
      {/* Existing documents */}
      <Card elevated className="p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-base font-semibold tracking-tight">Documents</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              {documents.length === 0
                ? "No documents uploaded yet."
                : `${documents.length} file${documents.length === 1 ? "" : "s"} on this deal.`}
            </p>
          </div>
        </div>

        {documents.length === 0 ? (
          <div className="py-10 text-center text-sm text-muted-foreground">
            <FileText className="h-6 w-6 mx-auto mb-2 opacity-60" />
            Upload a PDF to extract metrics and run scoring.
          </div>
        ) : (
          <ul className="divide-y divide-border/60">
            {documents.map((d) => (
              <li key={d.id} className="py-3 flex items-center gap-3 group">
                <div className="h-9 w-9 rounded-md bg-muted/60 ring-1 ring-border/70 grid place-items-center shrink-0">
                  <FileText className="h-4 w-4 text-muted-foreground" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium truncate">{d.filename}</div>
                  <div className="text-[11px] text-muted-foreground mt-0.5 flex items-center gap-2 flex-wrap">
                    <span className="uppercase tracking-wider">{d.doc_type.replace(/_/g, " ")}</span>
                    <span className="opacity-40">·</span>
                    <span>{d.page_count} pages</span>
                    {d.has_text && (
                      <>
                        <span className="opacity-40">·</span>
                        <span className="inline-flex items-center gap-1 text-success">
                          <CheckCircle2 className="h-3 w-3" />
                          Extracted
                        </span>
                      </>
                    )}
                    {d.extraction_quality?.quality_score != null && d.extraction_quality.quality_score < 80 && (
                      <>
                        <span className="opacity-40">·</span>
                        <span
                          className="inline-flex items-center gap-1 text-warning"
                          title={`Quality ${d.extraction_quality.quality_score}%. Pages with no usable text: ${
                            d.extraction_quality.empty_pages?.join(", ") || "—"
                          }`}
                        >
                          <span className="h-1.5 w-1.5 rounded-full bg-warning" />
                          Quality {d.extraction_quality.quality_score}%
                        </span>
                      </>
                    )}
                    {(d.extraction_quality?.ocr_pages ?? 0) > 0 && (
                      <>
                        <span className="opacity-40">·</span>
                        <span className="text-muted-foreground">
                          {d.extraction_quality?.ocr_pages} OCR {d.extraction_quality?.ocr_pages === 1 ? "page" : "pages"}
                        </span>
                      </>
                    )}
                  </div>
                </div>
                <button
                  onClick={() => deleteDoc(d.id, d.filename)}
                  className="opacity-0 group-hover:opacity-100 transition-opacity p-1.5 rounded-md hover:bg-destructive/10 text-muted-foreground hover:text-destructive"
                  aria-label="Delete document"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        )}

        {/* In-flight uploads */}
        <AnimatePresence>
          {uploads.length > 0 && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-4 pt-4 border-t border-border/60 space-y-3"
            >
              {uploads.map((u) => (
                <UploadRow key={u.id} upload={u} />
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </Card>

      {/* Dropzone */}
      <Card elevated className="p-6 flex flex-col">
        <h3 className="text-base font-semibold tracking-tight mb-1">Upload</h3>
        <p className="text-xs text-muted-foreground mb-4">
          PDF is best. We&apos;ll run OCR + table extraction automatically.
        </p>

        <div className="mb-4">
          <label className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
            Document type
          </label>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {DOC_TYPES.map((d) => (
              <button
                key={d.key}
                onClick={() => setDocType(d.key)}
                className={cn(
                  "px-2.5 h-7 rounded-full text-xs font-medium transition-colors",
                  docType === d.key
                    ? "bg-primary text-primary-foreground"
                    : "bg-secondary/60 text-muted-foreground hover:text-foreground hover:bg-secondary",
                )}
              >
                {d.label}
              </button>
            ))}
          </div>
        </div>

        <label
          onDragEnter={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDragOver={(e) => {
            e.preventDefault();
            if (!dragActive) setDragActive(true);
          }}
          onDrop={(e) => {
            e.preventDefault();
            setDragActive(false);
            if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
          }}
          className={cn(
            "relative flex-1 min-h-[180px] rounded-lg border border-dashed flex flex-col items-center justify-center text-center p-6 cursor-pointer transition-all",
            dragActive
              ? "border-primary bg-primary/5 scale-[1.01]"
              : "border-border/70 hover:border-border hover:bg-muted/20",
          )}
        >
          <input
            ref={inputRef}
            type="file"
            multiple
            accept="application/pdf,.pdf"
            className="sr-only"
            onChange={(e) => e.target.files && handleFiles(e.target.files)}
          />
          <div className="h-10 w-10 rounded-full bg-primary/10 ring-1 ring-primary/30 grid place-items-center mb-3">
            <Upload className="h-4 w-4 text-primary" />
          </div>
          <div className="text-sm font-medium">Drop files here</div>
          <div className="text-xs text-muted-foreground mt-1">or click to browse</div>
          <Button
            size="sm"
            variant="secondary"
            className="mt-4"
            onClick={(e) => {
              e.preventDefault();
              inputRef.current?.click();
            }}
          >
            <FileUp className="h-4 w-4" />
            Choose files
          </Button>
        </label>
      </Card>
    </div>
  );
}

function UploadRow({ upload }: { upload: Upload }) {
  return (
    <div className="flex items-center gap-3">
      <div className="h-8 w-8 rounded-md bg-muted/60 grid place-items-center shrink-0">
        {upload.status === "done" ? (
          <CheckCircle2 className="h-4 w-4 text-success" />
        ) : upload.status === "error" ? (
          <FileText className="h-4 w-4 text-destructive" />
        ) : (
          <Loader2 className="h-4 w-4 text-muted-foreground animate-spin" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium truncate">{upload.filename}</div>
        {upload.status === "done" ? (
          <div className="text-[11px] text-muted-foreground mt-1 flex items-center gap-2">
            {upload.ocr_pages! > 0 && (
              <span className="inline-flex items-center gap-1">
                <ScanText className="h-3 w-3" />
                {upload.ocr_pages} OCR
              </span>
            )}
            {upload.tables! > 0 && (
              <span className="inline-flex items-center gap-1">
                <TableIcon className="h-3 w-3" />
                {upload.tables} tables
              </span>
            )}
            {upload.images! > 0 && (
              <span className="inline-flex items-center gap-1">
                <ImageIcon className="h-3 w-3" />
                {upload.images} images
              </span>
            )}
          </div>
        ) : upload.status === "error" ? (
          <div className="text-xs text-destructive mt-0.5">{upload.error}</div>
        ) : (
          <div className="mt-1 h-1 rounded-full bg-muted overflow-hidden">
            <motion.div
              className="h-full bg-primary"
              initial={{ width: 0 }}
              animate={{ width: `${upload.progress}%` }}
              transition={{ duration: 0.2 }}
            />
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Upload a file with real progress via XHR (fetch doesn't yet expose upload
 * progress in a stable cross-browser way). Returns the API's JSON response.
 */
function uploadWithProgress(
  file: File,
  dealId: number,
  docType: string,
  onProgress: (pct: number) => void,
): Promise<{ extraction?: { ocr_pages?: number; tables?: number; images?: number } }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    form.append("file", file);
    form.append("doc_type", docType);

    xhr.open("POST", `/api/deals/${dealId}/documents/upload`);
    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) onProgress(Math.min(99, Math.round((e.loaded / e.total) * 100)));
    });
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch {
          resolve({});
        }
      } else {
        let detail = xhr.statusText;
        try {
          const b = JSON.parse(xhr.responseText);
          detail = b.detail ?? detail;
        } catch {}
        reject(new Error(detail));
      }
    };
    xhr.onerror = () => reject(new Error("Network error"));
    xhr.send(form);
  });
}
