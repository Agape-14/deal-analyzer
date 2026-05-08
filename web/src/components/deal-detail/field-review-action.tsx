"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Loader2, Pencil, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { FieldProvenance } from "@/lib/types";

export function FieldReviewAction({
  dealId,
  path,
  value,
  provenance,
}: {
  dealId?: number;
  path?: string;
  value: unknown;
  provenance?: FieldProvenance;
}) {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [draft, setDraft] = React.useState(() => scalarToInput(value));
  const [panelPos, setPanelPos] = React.useState<{ left: number; top: number } | null>(null);
  const wrapRef = React.useRef<HTMLDivElement>(null);
  const buttonRef = React.useRef<HTMLButtonElement>(null);

  React.useEffect(() => {
    setDraft(scalarToInput(value));
  }, [value]);

  React.useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onViewportChange() {
      setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    window.addEventListener("resize", onViewportChange);
    window.addEventListener("scroll", onViewportChange, true);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      window.removeEventListener("resize", onViewportChange);
      window.removeEventListener("scroll", onViewportChange, true);
    };
  }, [open]);

  if (!dealId || !path || !provenance || provenance.locked || !needsHumanReview(provenance) || !isEditableScalar(value)) {
    return null;
  }

  async function acceptAndLock() {
    if (!dealId || !path) return;
    setBusy(true);
    try {
      await api.post(`/api/deals/${dealId}/fields/edit`, {
        path,
        value,
        lock: true,
      });
      toast.success("Field approved and checks updated", { description: humanizePath(path) });
      setOpen(false);
      router.refresh();
    } catch (e) {
      toast.error("Couldn't approve field", { description: errorDetail(e) });
    } finally {
      setBusy(false);
    }
  }

  async function saveCorrection() {
    if (!dealId || !path) return;
    if (draft.trim() === "") {
      toast.error("Enter a corrected value first", { description: humanizePath(path) });
      return;
    }
    setSaving(true);
    try {
      await api.post(`/api/deals/${dealId}/fields/edit`, {
        path,
        value: parseDraftValue(draft, value),
        lock: true,
      });
      toast.success("Correction saved and checks updated", { description: humanizePath(path) });
      setOpen(false);
      router.refresh();
    } catch (e) {
      toast.error("Couldn't save correction", { description: errorDetail(e) });
    } finally {
      setSaving(false);
    }
  }

  function toggleOpen(e: React.MouseEvent<HTMLButtonElement>) {
    e.stopPropagation();
    const rect = buttonRef.current?.getBoundingClientRect();
    if (rect) {
      const width = 288;
      const margin = 12;
      setPanelPos({
        left: Math.max(margin, Math.min(rect.right - width, window.innerWidth - width - margin)),
        top: Math.min(rect.bottom + 8, window.innerHeight - 220),
      });
    }
    setOpen((v) => !v);
  }

  const confidence = typeof provenance.confidence === "number" ? provenance.confidence : null;
  const reason = reviewReason(provenance);

  return (
    <div ref={wrapRef} className="relative inline-flex">
      <button
        ref={buttonRef}
        type="button"
        onClick={toggleOpen}
        className="inline-flex h-5 items-center gap-1 rounded-full bg-warning/15 px-1.5 text-[10px] font-medium text-warning ring-1 ring-warning/30 transition-colors hover:bg-warning/25"
        title="Review or correct field"
      >
        <ShieldCheck className="h-2.5 w-2.5" />
        Review/edit
      </button>

      {open && (
        <div
          className="fixed z-[1000] w-72 rounded-lg border border-border/80 bg-popover p-3 text-[11px] leading-relaxed text-popover-foreground shadow-[0_20px_60px_-20px_rgba(0,0,0,0.9)]"
          style={panelPos ?? undefined}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-center gap-1.5 font-semibold">
            <ShieldCheck className="h-3.5 w-3.5 text-warning" />
            Low-confidence review
          </div>
          <div className="mt-2 rounded-md bg-warning/10 p-2 ring-1 ring-warning/20">
            <div className="text-[10px] uppercase tracking-[0.12em] text-warning/90">Reason</div>
            <div className="mt-1 text-foreground/90">{reason}</div>
            {confidence !== null && <div className="mt-1 text-muted-foreground">Confidence: {confidence}%</div>}
          </div>
          <div className="mt-2 rounded-md border border-border/70 bg-background/60 p-2">
            <div className="mb-1 text-[10px] uppercase tracking-[0.12em] text-muted-foreground">Correct value</div>
            <div className="flex items-center gap-2">
              <input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Enter value"
                className="h-8 min-w-0 flex-1 rounded-md border border-border bg-background px-2 text-xs outline-none focus:ring-2 focus:ring-ring"
              />
              <button
                type="button"
                onClick={saveCorrection}
                disabled={saving || busy}
                className={cn(
                  "inline-flex h-8 items-center gap-1 rounded-md bg-primary px-2 text-[11px] font-medium text-primary-foreground transition-colors hover:bg-primary/90",
                  (saving || busy) && "opacity-60",
                )}
              >
                {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Pencil className="h-3 w-3" />}
                Save
              </button>
            </div>
            <div className="mt-1 text-[10px] text-muted-foreground">{path}</div>
          </div>
          <div className="mt-2 text-muted-foreground">
            If the current value is already correct, approve it. If it is wrong, save the corrected value instead.
          </div>
          <div className="mt-2.5 flex items-center gap-1.5 border-t border-border/60 pt-2.5">
            <button
              type="button"
              onClick={acceptAndLock}
              disabled={busy || saving || value == null || value === ""}
              className={cn(
                "inline-flex items-center gap-1 rounded-md bg-primary/15 px-2 py-1 text-[11px] text-primary ring-1 ring-primary/30 transition-colors hover:bg-primary/25",
                (busy || saving || value == null || value === "") && "opacity-60",
              )}
            >
              {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
              Approve current
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded-md px-2 py-1 text-[11px] text-muted-foreground ring-1 ring-border transition-colors hover:bg-muted"
            >
              Leave pending
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function needsHumanReview(provenance: FieldProvenance): boolean {
  if (Array.isArray(provenance.conflict) && provenance.conflict.length > 1) return true;
  if (["wrong", "unverifiable", "missing", "stale"].includes(String(provenance.status))) return true;
  if (provenance.status === "confirmed") return typeof provenance.confidence === "number" && provenance.confidence < 85;
  if (provenance.status === "extracted") return typeof provenance.confidence !== "number" || provenance.confidence < 85;
  return false;
}

function reviewReason(provenance: FieldProvenance): string {
  if (Array.isArray(provenance.conflict) && provenance.conflict.length > 1) return "Documents disagree on this field.";
  if (provenance.status === "wrong") return "Verification corrected or challenged the extracted value.";
  if (provenance.status === "unverifiable") return "The verifier could not confirm this value in source documents.";
  if (provenance.status === "missing") return "The field was expected but not reliably extracted.";
  if (provenance.status === "stale") return "The field may be older than the latest uploaded documents.";
  if (typeof provenance.confidence === "number") return `Confidence is below the 85% approval threshold.`;
  return "This value has not reached the verified confidence threshold.";
}

function isEditableScalar(value: unknown): value is string | number | boolean | null {
  return value === null || ["string", "number", "boolean"].includes(typeof value);
}

function scalarToInput(value: unknown): string {
  if (value == null) return "";
  if (["string", "number", "boolean"].includes(typeof value)) return String(value);
  return "";
}

function parseDraftValue(value: string, original: unknown): string | number | boolean | null {
  const trimmed = value.trim().replace(/[$,%x]/gi, "").replace(/,/g, "");
  if (trimmed === "") return null;
  if (typeof original === "boolean") return ["true", "1", "yes"].includes(trimmed.toLowerCase());
  if (typeof original === "number" || /^-?\d+(\.\d+)?$/.test(trimmed)) return Number(trimmed);
  return value.trim();
}

function errorDetail(error: unknown): string {
  if (!error) return "The server did not return a reason.";
  const detail = (error as { detail?: unknown; message?: unknown })?.detail ?? (error as { message?: unknown })?.message;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (detail && typeof detail === "object") {
    try {
      return JSON.stringify(detail);
    } catch {
      return "The server returned an unreadable error.";
    }
  }
  return "The server did not return a reason.";
}

function humanizePath(path: string): string {
  const [, field = path] = path.split(".");
  return field.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}
