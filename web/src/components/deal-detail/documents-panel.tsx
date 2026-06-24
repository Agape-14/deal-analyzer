"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { PdfPreviewDialog, PreviewButton } from "@/components/deal-detail/pdf-preview";
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
  AlertCircle,
  Clock3,
} from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { DealDocument } from "@/lib/types";

type UploadState = {
  id: string;
  docId?: number;
  filename: string;
  status: "uploading" | "extracting" | "reviewing" | "done" | "error";
  progress: number;
  ocr_pages?: number;
  tables?: number;
  images?: number;
  error?: string;
};

type UploadResult = {
  id?: number;
  filename?: string;
  extraction?: {
    queued?: boolean;
    ocr_pages?: number;
    tables?: number;
    images?: number;
  };
};

type ExtractionQuality = NonNullable<DealDocument["extraction_quality"]> & {
  status?: string | null;
  error?: string | null;
  document_kind?: string | null;
};

const DOC_TYPES: Array<{ key: string; label: string }> = [
  { key: "offering_memo", label: "Offering Memo" },
  { key: "proforma", label: "Proforma" },
  { key: "market_study", label: "Market Study" },
  { key: "other", label: "Other" },
];

const ACCEPTED_UPLOAD_TYPES =
  "application/pdf,.pdf,.xlsx,.xlsm,.xls,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,text/csv";

const ACCEPTED_UPLOAD_EXTENSIONS = new Set([".pdf", ".xlsx", ".xlsm", ".xls", ".csv"]);

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
  const [uploads, setUploads] = React.useState<UploadState[]>([]);
  const [previewDoc, setPreviewDoc] = React.useState<DealDocument | null>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const dragDepth = React.useRef(0);
  const pendingExtractionIds = React.useRef<Set<string>>(new Set());
  const reviewReadyRef = React.useRef(false);
  const reviewStartLock = React.useRef(false);

  async function handleFiles(files: FileList | File[]) {
    const list = Array.from(files).filter((file) => {
      if (isAcceptedUpload(file)) return true;
      toast.error("Unsupported file type", {
        description: `${file.name} is not a PDF, Excel file, or CSV.`,
      });
      return false;
    });

    if (list.length === 0) return;

    const uploadItems = list.map((file) => ({
      file,
      localId: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    }));
    uploadItems.forEach(({ localId }) => pendingExtractionIds.current.add(localId));

    for (const { file, localId } of uploadItems) {
      setUploads((prev) => [...prev, { id: localId, filename: file.name, status: "uploading", progress: 0 }]);

      try {
        const result = await uploadWithProgress(file, dealId, docType, (p) => {
          setUploads((prev) => prev.map((u) => (u.id === localId ? { ...u, progress: p } : u)));
        });

        const queued = Boolean(result.extraction?.queued);
        setUploads((prev) =>
          prev.map((u) =>
            u.id === localId
              ? {
                  ...u,
                  docId: result.id,
                  status: queued ? "extracting" : "done",
                  progress: 100,
                  ocr_pages: result.extraction?.ocr_pages ?? 0,
                  tables: result.extraction?.tables ?? 0,
                  images: result.extraction?.images ?? 0,
                }
              : u,
          ),
        );

        toast.success("Document uploaded", {
          description: queued
            ? `${file.name} was saved. Reading the document now.`
            : `${file.name} was saved. Starting document review next.`,
        });
        router.refresh();

        if (queued && result.id) {
          void pollExtractionStatus(result.id, localId, file.name);
        } else {
          markUploadSettled(localId, file.name, true);
        }
      } catch (e) {
        const msg = (e as Error)?.message || "Upload failed";
        markUploadSettled(localId, file.name, false);
        setUploads((prev) => prev.map((u) => (u.id === localId ? { ...u, status: "error", error: msg } : u)));
        toast.error("Upload failed", { description: `${file.name}: ${msg}` });
      }
    }

    if (inputRef.current) inputRef.current.value = "";
  }

  function markUploadSettled(localId: string, filename: string, extracted: boolean) {
    pendingExtractionIds.current.delete(localId);
    if (extracted) reviewReadyRef.current = true;
    if (pendingExtractionIds.current.size === 0 && reviewReadyRef.current) {
      reviewReadyRef.current = false;
      void startDocumentReview(filename);
    }
  }

  async function startDocumentReview(filename: string) {
    if (reviewStartLock.current) return;
    reviewStartLock.current = true;
    setUploads((prev) => prev.map((u) => (u.status === "done" ? { ...u, status: "reviewing" } : u)));

    try {
      await delay(1000);
      const res = await fetch(`/api/deals/${dealId}/review`, {
        method: "POST",
        cache: "no-store",
        credentials: "include",
        headers: { Accept: "application/json" },
      });
      if (!res.ok) throw new Error(await responseErrorMessage(res));
      toast.success("Document review started", {
        description: "Reading documents, checking sources, math-checking, and updating the score.",
      });
      router.refresh();
    } catch (e) {
      setUploads((prev) =>
        prev.map((u) => (u.status === "reviewing" ? { ...u, status: "done" } : u)),
      );
      toast.error("Document review did not start", {
        description: `${filename}: ${(e as Error)?.message || "Use Review documents again."}`,
      });
    } finally {
      window.setTimeout(() => {
        reviewStartLock.current = false;
      }, 5000);
    }
  }

  async function pollExtractionStatus(docId: number, localId: string, filename: string) {
    const attempts = 60;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      await delay(attempt === 0 ? 3000 : 5000);

      try {
        const doc = await fetchDocument(dealId, docId);
        if (!doc) continue;

        const quality = getExtractionQuality(doc);
        if (quality?.status === "error") {
          const message = quality.error || "Extraction failed after the upload was saved.";
          markUploadSettled(localId, filename, false);
          setUploads((prev) =>
            prev.map((u) => (u.id === localId ? { ...u, status: "error", error: message } : u)),
          );
          toast.error("Extraction failed", { description: `${filename}: ${message}` });
          router.refresh();
          return;
        }

        if (doc.has_text) {
          const extractionError = await fetchExtractionError(doc.id);
          if (extractionError) {
            markUploadSettled(localId, filename, false);
            setUploads((prev) =>
              prev.map((u) => (u.id === localId ? { ...u, status: "error", error: extractionError } : u)),
            );
            toast.error("Extraction failed", { description: `${filename}: ${extractionError}` });
            router.refresh();
            return;
          }

          setUploads((prev) =>
            prev.map((u) =>
              u.id === localId
                ? {
                    ...u,
                    status: "done",
                    progress: 100,
                    ocr_pages: quality?.ocr_pages ?? 0,
                  }
                : u,
            ),
          );
          toast.success("Extraction complete", { description: `${filename} is ready. Document review will start automatically.` });
          markUploadSettled(localId, filename, true);
          router.refresh();
          return;
        }

        setUploads((prev) =>
          prev.map((u) =>
            u.id === localId
              ? { ...u, status: "extracting", progress: Math.min(99, Math.max(u.progress, 35 + attempt)) }
              : u,
          ),
        );
      } catch (e) {
        if (attempt >= 2) {
          const msg = (e as Error)?.message || "Could not check extraction status.";
          setUploads((prev) => prev.map((u) => (u.id === localId ? { ...u, error: msg } : u)));
        }
      }
    }

    markUploadSettled(localId, filename, false);
    setUploads((prev) =>
      prev.map((u) =>
        u.id === localId
          ? {
              ...u,
              status: "error",
              error: "Extraction is taking longer than expected. Refresh this page in a few minutes, or try reprocessing the document.",
            }
          : u,
      ),
    );
    toast.warning("Extraction is still running", {
      description: `${filename} was uploaded, but extraction has not finished yet.`,
    });
    router.refresh();
  }

  function handleDragEnter(e: React.DragEvent<HTMLElement>) {
    if (!hasDraggedFiles(e)) return;
    e.preventDefault();
    e.stopPropagation();
    dragDepth.current += 1;
    setDragActive(true);
  }

  function handleDragLeave(e: React.DragEvent<HTMLElement>) {
    if (!hasDraggedFiles(e)) return;
    e.preventDefault();
    e.stopPropagation();
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragActive(false);
  }

  function handleDragOver(e: React.DragEvent<HTMLElement>) {
    if (!hasDraggedFiles(e)) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "copy";
    if (!dragActive) setDragActive(true);
  }

  function handleDrop(e: React.DragEvent<HTMLElement>) {
    if (!hasDraggedFiles(e)) return;
    e.preventDefault();
    e.stopPropagation();
    dragDepth.current = 0;
    setDragActive(false);
    if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
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
    <div
      className="relative grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-6"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {dragActive && (
        <div className="pointer-events-none absolute inset-0 z-10 rounded-xl border-2 border-dashed border-primary bg-primary/5 shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.25)]" />
      )}
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
            Upload a PDF, Excel model, or CSV to extract metrics and run scoring.
          </div>
        ) : (
          <ul className="divide-y divide-border/60">
            {documents.map((d) => {
              const status = documentStatus(d);
              return (
                <li key={d.id} className="py-3 flex items-center gap-3 group">
                  <div className="h-9 w-9 rounded-md bg-muted/60 ring-1 ring-border/70 grid place-items-center shrink-0">
                    <FileText className="h-4 w-4 text-muted-foreground" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <button
                      onClick={() => setPreviewDoc(d)}
                      className="text-sm font-medium truncate text-left hover:text-primary transition-colors"
                      title="Preview document"
                    >
                      {d.filename}
                    </button>
                    <div className="text-[11px] text-muted-foreground mt-0.5 flex items-center gap-2 flex-wrap">
                      <span className="uppercase tracking-wider">{d.doc_type.replace(/_/g, " ")}</span>
                      <span className="opacity-40">-</span>
                      <span>
                        {d.page_count} {docUnit(d.filename, d.page_count)}
                      </span>
                      {status && (
                        <>
                          <span className="opacity-40">-</span>
                          <span className={cn("inline-flex items-center gap-1", status.className)}>
                            <status.icon className="h-3 w-3" />
                            {status.label}
                          </span>
                        </>
                      )}
                      {d.extraction_quality?.quality_score != null && d.extraction_quality.quality_score < 80 && (
                        <>
                          <span className="opacity-40">-</span>
                          <span
                            className="inline-flex items-center gap-1 text-warning"
                            title={`Quality ${d.extraction_quality.quality_score}%. Pages with no usable text: ${
                              d.extraction_quality.empty_pages?.join(", ") || "none"
                            }`}
                          >
                            <span className="h-1.5 w-1.5 rounded-full bg-warning" />
                            Quality {d.extraction_quality.quality_score}%
                          </span>
                        </>
                      )}
                      {(d.extraction_quality?.ocr_pages ?? 0) > 0 && (
                        <>
                          <span className="opacity-40">-</span>
                          <span className="text-muted-foreground">
                            {d.extraction_quality?.ocr_pages} OCR {d.extraction_quality?.ocr_pages === 1 ? "page" : "pages"}
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                    <PreviewButton doc={d} onOpen={(doc) => setPreviewDoc(doc)} />
                    <button
                      onClick={() => deleteDoc(d.id, d.filename)}
                      className="p-1.5 rounded-md hover:bg-destructive/10 text-muted-foreground hover:text-destructive"
                      aria-label="Delete document"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}

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

      <Card elevated className="p-6 flex flex-col">
        <h3 className="text-base font-semibold tracking-tight mb-1">Upload</h3>
        <p className="text-xs text-muted-foreground mb-4">
          Upload PDFs, Excel models, or CSVs. We&apos;ll extract text, tables, sheets, and formulas automatically.
        </p>

        <div className="mb-4">
          <label className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">Document type</label>
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
            accept={ACCEPTED_UPLOAD_TYPES}
            className="sr-only"
            onChange={(e) => e.target.files && handleFiles(e.target.files)}
          />
          <div className="h-10 w-10 rounded-full bg-primary/10 ring-1 ring-primary/30 grid place-items-center mb-3">
            <Upload className="h-4 w-4 text-primary" />
          </div>
          <div className="text-sm font-medium">Drop files here</div>
          <div className="text-xs text-muted-foreground mt-1">PDF, Excel, CSV</div>
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

      <PdfPreviewDialog doc={previewDoc} open={previewDoc !== null} onOpenChange={(o) => !o && setPreviewDoc(null)} />
    </div>
  );
}

function UploadRow({ upload }: { upload: UploadState }) {
  return (
    <div className="flex items-center gap-3">
      <div className="h-8 w-8 rounded-md bg-muted/60 grid place-items-center shrink-0">
        {upload.status === "done" ? (
          <CheckCircle2 className="h-4 w-4 text-success" />
        ) : upload.status === "error" ? (
          <AlertCircle className="h-4 w-4 text-destructive" />
        ) : (
          <Loader2 className="h-4 w-4 text-muted-foreground animate-spin" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium truncate">{upload.filename}</div>
        {upload.status === "done" ? (
          <div className="text-[11px] text-success mt-0.5">Extraction complete</div>
        ) : upload.status === "error" ? (
          <div className="text-xs text-destructive mt-0.5">{upload.error}</div>
        ) : upload.status === "reviewing" ? (
          <div className="text-xs text-muted-foreground mt-0.5">Starting document review...</div>
        ) : upload.status === "extracting" ? (
          <div className="text-xs text-muted-foreground mt-0.5">Saved. Reading document...</div>
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

function uploadWithProgress(
  file: File,
  dealId: number,
  docType: string,
  onProgress: (pct: number) => void,
): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    form.append("file", file);
    form.append("doc_type", docType);

    xhr.open("POST", `/document-upload/deals/${dealId}/documents`);
    xhr.withCredentials = true;
    xhr.timeout = 120000;
    xhr.setRequestHeader("Accept", "application/json");
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
        reject(new Error(uploadErrorMessage(xhr)));
      }
    };
    xhr.onerror = () => reject(new Error("Network error. Check your connection and try the upload again."));
    xhr.ontimeout = () => reject(new Error("Upload timed out before the server responded. Try a smaller file or upload again."));
    xhr.onabort = () => reject(new Error("Upload canceled."));
    xhr.send(form);
  });
}

async function fetchDocument(dealId: number, docId: number): Promise<DealDocument | null> {
  const res = await fetch(`/api/deals/${dealId}/documents`, {
    cache: "no-store",
    credentials: "include",
  });
  if (!res.ok) throw new Error(`Status check failed with HTTP ${res.status}`);
  const docs = (await res.json()) as DealDocument[];
  return docs.find((doc) => doc.id === docId) ?? null;
}

async function fetchExtractionError(docId: number): Promise<string | null> {
  const res = await fetch(`/api/deals/documents/${docId}/text`, {
    cache: "no-store",
    credentials: "include",
  });
  if (!res.ok) return null;
  const body = (await res.json()) as { text?: unknown };
  const text = typeof body.text === "string" ? body.text.trim() : "";
  if (text.toLowerCase().startsWith("error extracting text:")) {
    return text.replace(/^error extracting text:\s*/i, "") || "Extraction failed.";
  }
  return null;
}

async function responseErrorMessage(res: Response): Promise<string> {
  const status = `HTTP ${res.status}${res.statusText ? ` ${res.statusText}` : ""}`;
  const raw = (await res.text()).trim();
  if (!raw) return status;
  try {
    const body = JSON.parse(raw) as { detail?: unknown; message?: unknown } | unknown;
    const detail =
      body && typeof body === "object" && ("detail" in body || "message" in body)
        ? (body as { detail?: unknown; message?: unknown }).detail ??
          (body as { detail?: unknown; message?: unknown }).message
        : body;
    if (typeof detail === "string") return `${status}: ${detail}`;
    return `${status}: ${JSON.stringify(detail)}`;
  } catch {
    return `${status}: ${raw.slice(0, 300)}`;
  }
}

function uploadErrorMessage(xhr: XMLHttpRequest): string {
  const status = xhr.status
    ? `HTTP ${xhr.status}${xhr.statusText ? ` ${xhr.statusText}` : ""}`
    : "Upload request failed";
  const raw = (xhr.responseText || "").trim();
  if (!raw) {
    return xhr.status ? status : "Upload request failed before the server returned a response.";
  }

  try {
    const body = JSON.parse(raw) as { detail?: unknown; message?: unknown } | unknown;
    const detail =
      body && typeof body === "object" && ("detail" in body || "message" in body)
        ? (body as { detail?: unknown; message?: unknown }).detail ??
          (body as { detail?: unknown; message?: unknown }).message
        : body;
    if (typeof detail === "string") return `${status}: ${detail}`;
    return `${status}: ${JSON.stringify(detail)}`;
  } catch {
    return `${status}: ${raw.slice(0, 300)}`;
  }
}

function documentStatus(doc: DealDocument): { label: string; className: string; icon: React.ElementType } | null {
  const quality = getExtractionQuality(doc);
  if (quality?.status === "error") {
    return { label: "Extraction failed", className: "text-destructive", icon: AlertCircle };
  }
  if (doc.has_text) {
    return { label: "Extracted", className: "text-success", icon: CheckCircle2 };
  }
  if (quality) {
    return { label: "Extracting", className: "text-warning", icon: Clock3 };
  }
  return { label: "Pending", className: "text-muted-foreground", icon: Clock3 };
}

function getExtractionQuality(doc: DealDocument): ExtractionQuality | null {
  return (doc.extraction_quality ?? null) as ExtractionQuality | null;
}

function docUnit(filename: string, count: number): string {
  const lower = filename.toLowerCase();
  const singular = lower.endsWith(".xlsx") || lower.endsWith(".xlsm") || lower.endsWith(".xls") || lower.endsWith(".csv") ? "sheet" : "page";
  return count === 1 ? singular : `${singular}s`;
}

function hasDraggedFiles(e: React.DragEvent<HTMLElement>): boolean {
  return Array.from(e.dataTransfer.types ?? []).includes("Files");
}

function isAcceptedUpload(file: File): boolean {
  const lower = file.name.toLowerCase();
  const dot = lower.lastIndexOf(".");
  const ext = dot >= 0 ? lower.slice(dot) : "";
  return ACCEPTED_UPLOAD_EXTENSIONS.has(ext);
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
