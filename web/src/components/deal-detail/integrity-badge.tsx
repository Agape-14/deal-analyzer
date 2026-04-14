"use client";

import * as React from "react";
import { CheckCircle2, AlertTriangle, Sparkles, Lock, Calculator, UserSquare, HelpCircle, FileText } from "lucide-react";
import type { FieldProvenance } from "@/lib/types";
import { cn, fmtDate } from "@/lib/utils";

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
 * On hover shows a small tooltip card with source filename, page, timestamp,
 * and conflict details when the field disagrees across documents.
 */
export function IntegrityBadge({
  provenance,
  compact = false,
}: {
  provenance?: FieldProvenance;
  compact?: boolean;
}) {
  const [open, setOpen] = React.useState(false);

  if (!provenance) return null;

  const status = provenance.status ?? "extracted";
  const locked = provenance.locked;
  const hasConflict = Array.isArray(provenance.conflict) && provenance.conflict.length > 1;

  const ui = iconFor(status, hasConflict);
  const label = labelFor(status, hasConflict);

  return (
    <span className="relative inline-flex" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <span
        className={cn(
          "inline-flex items-center justify-center rounded-full",
          compact ? "h-4 w-4" : "h-5 w-5",
          ui.bg,
          ui.color,
          "ring-1",
          ui.ring,
        )}
        title={label}
      >
        {locked ? <Lock className={compact ? "h-2.5 w-2.5" : "h-3 w-3"} /> : <ui.Icon className={compact ? "h-2.5 w-2.5" : "h-3 w-3"} />}
      </span>

      {open && (
        <span
          role="tooltip"
          className="absolute left-1/2 -translate-x-1/2 top-full mt-1.5 z-50 w-64 rounded-lg border border-border/80 bg-popover text-popover-foreground shadow-[0_20px_60px_-20px_rgba(0,0,0,0.9)] p-3 text-[11px] leading-relaxed pointer-events-none"
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

          {provenance.source_doc_name && (
            <div className="flex items-center gap-1 text-muted-foreground">
              <FileText className="h-3 w-3 shrink-0" />
              <span className="truncate">
                {provenance.source_doc_name}
                {provenance.source_page ? ` · p.${provenance.source_page}` : ""}
              </span>
            </div>
          )}
          {provenance.verification_note && (
            <div className="mt-1 text-foreground/90">&ldquo;{provenance.verification_note}&rdquo;</div>
          )}
          {provenance.verification_source && !provenance.verification_note && (
            <div className="mt-1 text-foreground/90">&ldquo;{provenance.verification_source}&rdquo;</div>
          )}
          {provenance.extracted_at && (
            <div className="mt-1 text-muted-foreground">Extracted {fmtDate(provenance.extracted_at)}</div>
          )}
          {provenance.verified_at && (
            <div className="text-muted-foreground">
              Verified {fmtDate(provenance.verified_at)}
              {typeof provenance.confidence === "number" && ` · ${provenance.confidence}% confidence`}
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
        </span>
      )}
    </span>
  );
}

function iconFor(status: string, hasConflict: boolean) {
  if (hasConflict) return { Icon: AlertTriangle, bg: "bg-destructive/15", color: "text-destructive", ring: "ring-destructive/30" };
  switch (status) {
    case "confirmed":
      return { Icon: CheckCircle2, bg: "bg-success/15", color: "text-success", ring: "ring-success/30" };
    case "wrong":
      return { Icon: AlertTriangle, bg: "bg-destructive/15", color: "text-destructive", ring: "ring-destructive/30" };
    case "unverifiable":
      return { Icon: HelpCircle, bg: "bg-muted", color: "text-muted-foreground", ring: "ring-border" };
    case "calculated":
      return { Icon: Calculator, bg: "bg-chart-3/15", color: "text-[hsl(var(--chart-3))]", ring: "ring-[hsl(var(--chart-3))/.3]" };
    case "manual":
      return { Icon: UserSquare, bg: "bg-primary/15", color: "text-primary", ring: "ring-primary/30" };
    case "extracted":
    default:
      return { Icon: Sparkles, bg: "bg-muted", color: "text-muted-foreground", ring: "ring-border" };
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
