"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Loader2, ShieldCheck } from "lucide-react";
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
  const wrapRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
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
      toast.success("Field approved and locked", { description: humanizePath(path) });
      setOpen(false);
      router.refresh();
    } catch (e) {
      toast.error("Couldn't approve field", { description: (e as { detail?: string })?.detail });
    } finally {
      setBusy(false);
    }
  }

  const confidence = typeof provenance.confidence === "number" ? provenance.confidence : null;
  const reason = reviewReason(provenance);

  return (
    <div ref={wrapRef} className="relative inline-flex">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="inline-flex h-5 items-center gap-1 rounded-full bg-warning/15 px-1.5 text-[10px] font-medium text-warning ring-1 ring-warning/30 transition-colors hover:bg-warning/25"
        title="Review low-confidence field"
      >
        <ShieldCheck className="h-2.5 w-2.5" />
        Review
      </button>

      {open && (
        <div
          className="absolute right-0 top-full z-50 mt-1.5 w-72 rounded-lg border border-border/80 bg-popover p-3 text-[11px] leading-relaxed text-popover-foreground shadow-[0_20px_60px_-20px_rgba(0,0,0,0.9)]"
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
          <div className="mt-2 text-muted-foreground">
            Approving this locks the current value so future extraction runs cannot overwrite it automatically.
          </div>
          <div className="mt-2.5 flex items-center gap-1.5 border-t border-border/60 pt-2.5">
            <button
              type="button"
              onClick={acceptAndLock}
              disabled={busy}
              className={cn(
                "inline-flex items-center gap-1 rounded-md bg-primary/15 px-2 py-1 text-[11px] text-primary ring-1 ring-primary/30 transition-colors hover:bg-primary/25",
                busy && "opacity-60",
              )}
            >
              {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
              Approve & lock
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

function humanizePath(path: string): string {
  const [, field = path] = path.split(".");
  return field.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}
