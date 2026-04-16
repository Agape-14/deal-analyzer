"use client";

import * as React from "react";
import {
  CheckCircle2,
  AlertTriangle,
  Sparkles,
  Lock,
  Calculator,
  UserSquare,
  HelpCircle,
  FileText,
  Undo2,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";
import type { FieldProvenance } from "@/lib/types";
import { cn, fmtDate } from "@/lib/utils";
import { api } from "@/lib/api";
import { useRouter } from "next/navigation";

/**
 * Small badge rendered next to a metric row to communicate data provenance.
 *
 *   confirmed    → green check
 *   wrong        → red warn (value was corrected by /verify)
 *   unverifiable → gray ? (couldn't be confirmed against source docs)
 *   calculated   → blue abacus icon
 *   manual       → user icon (manually edited; usually also locked)
 *   extracted    → sparkles (default — extracted but not yet verified)
 *
 * Click to open a popover with full provenance: source document, page,
 * timestamps, conflict details, and — for wrong-flagged fields that
 * were auto-corrected — the previous value plus a Revert button.
 * Hovering still opens the popover (keeps the existing muscle memory)
 * but a sticky click-to-keep-open mode is what actually makes wrong
 * flags actionable.
 */
export function IntegrityBadge({
  provenance,
  compact = false,
  dealId,
  path,
}: {
  provenance?: FieldProvenance;
  compact?: boolean;
  dealId?: number;
  path?: string;
}) {
  const router = useRouter();
  const [hover, setHover] = React.useState(false);
  const [clicked, setClicked] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const wrapRef = React.useRef<HTMLSpanElement>(null);

  // Close the clicked-open popover when clicking outside.
  React.useEffect(() => {
    if (!clicked) return;
    function onDocClick(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setClicked(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [clicked]);

  if (!provenance) return null;

  const status = provenance.status ?? "extracted";
  const locked = provenance.locked;
  const hasConflict = Array.isArray(provenance.conflict) && provenance.conflict.length > 1;

  const ui = iconFor(status, hasConflict);
  const label = labelFor(status, hasConflict);

  // "wrong" status with a previous_value means the verifier caught a
  // bad extraction and auto-corrected it. Show both values and a
  // revert button so the human can override Claude's correction.
  const wasCorrected =
    status === "wrong" &&
    Object.prototype.hasOwnProperty.call(provenance, "previous_value") &&
    provenance.previous_value !== undefined &&
    provenance.previous_value !== null;

  const open = hover || clicked;

  async function revertToPrevious() {
    if (!dealId || !path || provenance?.previous_value === undefined) return;
    const [section, ...rest] = path.split(".");
    const field = rest.join(".");
    setBusy(true);
    try {
      await api.post(`/api/deals/${dealId}/fields/edit`, {
        section,
        field,
        value: provenance.previous_value,
        lock: true,
      });
      toast.success("Reverted to original value");
      setClicked(false);
      router.refresh();
    } catch (e) {
      toast.error("Couldn't revert", { description: (e as { detail?: string })?.detail });
    } finally {
      setBusy(false);
    }
  }

  async function lockCurrent() {
    if (!dealId || !path) return;
    setBusy(true);
    try {
      await api.post(`/api/deals/${dealId}/fields/lock`, {
        section: path.split(".")[0],
        field: path.split(".").slice(1).join("."),
        locked: true,
      });
      toast.success("Correction accepted & locked");
      setClicked(false);
      router.refresh();
    } catch (e) {
      toast.error("Couldn't lock", { description: (e as { detail?: string })?.detail });
    } finally {
      setBusy(false);
    }
  }

  return (
    <span
      ref={wrapRef}
      className="relative inline-flex"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setClicked((v) => !v);
        }}
        className={cn(
          "inline-flex items-center justify-center rounded-full transition-colors hover:brightness-125",
          compact ? "h-4 w-4" : "h-5 w-5",
          ui.bg,
          ui.color,
          "ring-1",
          ui.ring,
        )}
        title={label}
      >
        {locked ? (
          <Lock className={compact ? "h-2.5 w-2.5" : "h-3 w-3"} />
        ) : (
          <ui.Icon className={compact ? "h-2.5 w-2.5" : "h-3 w-3"} />
        )}
      </button>

      {open && (
        <span
          role="tooltip"
          className={cn(
            "absolute left-1/2 -translate-x-1/2 top-full mt-1.5 z-50 w-72 rounded-lg border border-border/80 bg-popover text-popover-foreground shadow-[0_20px_60px_-20px_rgba(0,0,0,0.9)] p-3 text-[11px] leading-relaxed",
            // Clicked state gets pointer events so buttons work;
            // hover state stays pointer-events-none so it doesn't
            // eat clicks outside.
            clicked ? "pointer-events-auto" : "pointer-events-none",
          )}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-center gap-1.5 font-semibold mb-1.5">
            <ui.Icon className="h-3.5 w-3.5" />
            {label}
            {locked && (
              <span className="ml-auto inline-flex items-center gap-1 text-[10px] font-medium text-primary">
                <Lock className="h-2.5 w-2.5" /> locked
              </span>
            )}
          </div>

          {/* Correction detail: extracted value → corrected value */}
          {wasCorrected && (
            <div className="mb-2 rounded-md bg-destructive/10 ring-1 ring-destructive/20 p-2">
              <div className="text-[10px] uppercase tracking-widest text-destructive/80 mb-1">
                Corrected
              </div>
              <div className="flex items-center gap-2">
                <span className="line-through text-muted-foreground tabular-nums">
                  {formatForDisplay(provenance.previous_value)}
                </span>
                <span className="text-muted-foreground">→</span>
                <span className="font-medium tabular-nums">
                  {formatForDisplay(provenance.corrected_value)}
                </span>
              </div>
              {provenance.correction_note && (
                <div className="mt-1.5 text-foreground/90">
                  &ldquo;{provenance.correction_note}&rdquo;
                </div>
              )}
              {provenance.correction_source && !provenance.correction_note && (
                <div className="mt-1.5 text-foreground/90">
                  &ldquo;{provenance.correction_source}&rdquo;
                </div>
              )}
            </div>
          )}

          {provenance.source_doc_name && (
            <div className="flex items-center gap-1 text-muted-foreground">
              <FileText className="h-3 w-3 shrink-0" />
              <span className="truncate">
                {provenance.source_doc_name}
                {provenance.source_page ? ` · p.${provenance.source_page}` : ""}
              </span>
            </div>
          )}
          {provenance.verification_note && !wasCorrected && (
            <div className="mt-1 text-foreground/90">
              &ldquo;{provenance.verification_note}&rdquo;
            </div>
          )}
          {provenance.verification_source && !provenance.verification_note && !wasCorrected && (
            <div className="mt-1 text-foreground/90">
              &ldquo;{provenance.verification_source}&rdquo;
            </div>
          )}
          {provenance.extracted_at && (
            <div className="mt-1 text-muted-foreground">
              Extracted {fmtDate(provenance.extracted_at)}
            </div>
          )}
          {provenance.verified_at && (
            <div className="text-muted-foreground">
              Verified {fmtDate(provenance.verified_at)}
              {typeof provenance.confidence === "number" &&
                ` · ${provenance.confidence}% confidence`}
            </div>
          )}

          {hasConflict && provenance.conflict && (
            <div className="mt-2 border-t border-border/60 pt-2">
              <div className="text-destructive font-medium mb-1">Conflicting across documents</div>
              <ul className="space-y-0.5">
                {provenance.conflict.slice(0, 4).map((c, i) => (
                  <li key={i} className="flex justify-between gap-2">
                    <span className="truncate text-muted-foreground">{c.doc_name}</span>
                    <span className="tabular-nums font-medium">{String(c.value)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Actions — only visible once the popover is click-opened
              (so passive hovers don't show buttons) and only when we
              have enough context to call the edit endpoint. */}
          {clicked && wasCorrected && dealId && path && !locked && (
            <div className="mt-2.5 pt-2.5 border-t border-border/60 flex items-center gap-1.5">
              <button
                type="button"
                onClick={revertToPrevious}
                disabled={busy}
                className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md ring-1 ring-border hover:bg-muted transition-colors disabled:opacity-50"
              >
                {busy ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Undo2 className="h-3 w-3" />
                )}
                Revert to original
              </button>
              <button
                type="button"
                onClick={lockCurrent}
                disabled={busy}
                className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md bg-primary/15 text-primary ring-1 ring-primary/30 hover:bg-primary/25 transition-colors disabled:opacity-50"
              >
                {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Lock className="h-3 w-3" />}
                Keep &amp; lock
              </button>
            </div>
          )}
        </span>
      )}
    </span>
  );
}

function formatForDisplay(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "object") {
    try {
      return JSON.stringify(v);
    } catch {
      return String(v);
    }
  }
  return String(v);
}

function iconFor(status: string, hasConflict: boolean) {
  if (hasConflict)
    return {
      Icon: AlertTriangle,
      bg: "bg-destructive/15",
      color: "text-destructive",
      ring: "ring-destructive/30",
    };
  switch (status) {
    case "confirmed":
      return {
        Icon: CheckCircle2,
        bg: "bg-success/15",
        color: "text-success",
        ring: "ring-success/30",
      };
    case "wrong":
      return {
        Icon: AlertTriangle,
        bg: "bg-destructive/15",
        color: "text-destructive",
        ring: "ring-destructive/30",
      };
    case "unverifiable":
      return {
        Icon: HelpCircle,
        bg: "bg-muted",
        color: "text-muted-foreground",
        ring: "ring-border",
      };
    case "calculated":
      return {
        Icon: Calculator,
        bg: "bg-chart-3/15",
        color: "text-[hsl(var(--chart-3))]",
        ring: "ring-[hsl(var(--chart-3))/.3]",
      };
    case "manual":
      return {
        Icon: UserSquare,
        bg: "bg-primary/15",
        color: "text-primary",
        ring: "ring-primary/30",
      };
    case "extracted":
    default:
      return {
        Icon: Sparkles,
        bg: "bg-muted",
        color: "text-muted-foreground",
        ring: "ring-border",
      };
  }
}

function labelFor(status: string, hasConflict: boolean) {
  if (hasConflict) return "Conflicting across documents";
  switch (status) {
    case "confirmed":
      return "Verified against source document";
    case "wrong":
      return "Corrected by verification";
    case "unverifiable":
      return "Couldn't confirm in source docs";
    case "calculated":
      return "Derived from other metrics";
    case "manual":
      return "Manually edited";
    case "missing":
      return "Found in source but not extracted";
    default:
      return "Extracted (not yet verified)";
  }
}
