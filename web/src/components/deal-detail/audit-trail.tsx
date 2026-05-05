"use client";

import { AlertTriangle, CheckCircle2, Clock3, FileText, Lock, PencilLine, Sparkles } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn, fmtDate } from "@/lib/utils";
import type { DealDetail, FieldProvenance } from "@/lib/types";

type AuditEvent = {
  at: string | null;
  path: string;
  label: string;
  kind: "extracted" | "verified" | "corrected" | "manual" | "conflict" | "unverifiable";
  detail: string;
  source?: string;
};

export function AuditTrail({ deal }: { deal: DealDetail }) {
  const provenance = deal.metrics?._provenance ?? {};
  const events = buildEvents(provenance).slice(0, 12);

  if (events.length === 0) return null;

  return (
    <Card elevated className="p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold tracking-tight">Field audit trail</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Recent extraction, verification, correction, conflict, and lock events for deal metrics.
          </p>
        </div>
        <div className="hidden sm:flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground ring-1 ring-border">
          <Clock3 className="h-4 w-4" />
        </div>
      </div>

      <div className="mt-5 divide-y divide-border/60 rounded-lg border border-border/70 overflow-hidden">
        {events.map((event, index) => {
          const ui = eventUi(event.kind);
          return (
            <div key={`${event.path}-${event.kind}-${index}`} className="grid grid-cols-[auto_1fr] gap-3 bg-background/30 px-4 py-3">
              <div className={cn("mt-0.5 grid h-7 w-7 place-items-center rounded-md ring-1", ui.className)}>
                <ui.Icon className="h-3.5 w-3.5" />
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-sm font-medium tracking-tight">{event.label}</span>
                  <span className={cn("rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider ring-1", ui.className)}>
                    {ui.label}
                  </span>
                  {event.at && <span className="text-[11px] text-muted-foreground">{fmtDate(event.at)}</span>}
                </div>
                <div className="mt-1 text-xs leading-relaxed text-muted-foreground">{event.detail}</div>
                {event.source && (
                  <div className="mt-1 inline-flex max-w-full items-center gap-1.5 text-[11px] text-muted-foreground">
                    <FileText className="h-3 w-3 shrink-0" />
                    <span className="truncate">{event.source}</span>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function buildEvents(provenance: Record<string, FieldProvenance>): AuditEvent[] {
  const events: AuditEvent[] = [];
  for (const [path, prov] of Object.entries(provenance)) {
    const label = humanizePath(path);
    const source = sourceLabel(prov);

    if (prov.extracted_at) {
      events.push({
        at: prov.extracted_at,
        path,
        label,
        kind: "extracted",
        detail: `Extracted value from ${prov.source_doc_name || "source document"}.`,
        source,
      });
    }

    if (prov.verified_at) {
      const status = String(prov.status || "verified");
      events.push({
        at: prov.verified_at,
        path,
        label,
        kind: status === "wrong" ? "corrected" : status === "unverifiable" ? "unverifiable" : "verified",
        detail: verificationDetail(prov),
        source,
      });
    }

    if (prov.previous_value !== undefined && prov.previous_value !== null) {
      events.push({
        at: prov.verified_at || prov.extracted_at || null,
        path,
        label,
        kind: "corrected",
        detail: `Corrected from ${formatRaw(prov.previous_value)} to ${formatRaw(prov.corrected_value)}.`,
        source,
      });
    }

    if (prov.locked) {
      events.push({
        at: prov.verified_at || prov.extracted_at || null,
        path,
        label,
        kind: "manual",
        detail: "Field is locked against automatic overwrite.",
        source,
      });
    }

    if (Array.isArray(prov.conflict) && prov.conflict.length > 1) {
      events.push({
        at: prov.extracted_at || null,
        path,
        label,
        kind: "conflict",
        detail: `${prov.conflict.length} source values disagree for this field.`,
        source,
      });
    }
  }

  return events.sort((a, b) => dateMs(b.at) - dateMs(a.at));
}

function verificationDetail(prov: FieldProvenance): string {
  if (prov.status === "wrong") return prov.correction_note || prov.verification_note || "Verifier corrected the extracted value.";
  if (prov.status === "unverifiable") return prov.verification_note || "Verifier could not confirm this value in source documents.";
  if (prov.status === "confirmed") return `Confirmed against source${typeof prov.confidence === "number" ? ` at ${prov.confidence}% confidence` : ""}.`;
  if (prov.status === "calculated") return "Calculated from other extracted or verified fields.";
  return prov.verification_note || "Verification updated this field.";
}

function eventUi(kind: AuditEvent["kind"]) {
  switch (kind) {
    case "verified":
      return { Icon: CheckCircle2, label: "Verified", className: "bg-success/15 text-success ring-success/30" };
    case "corrected":
      return { Icon: AlertTriangle, label: "Corrected", className: "bg-destructive/15 text-destructive ring-destructive/30" };
    case "manual":
      return { Icon: Lock, label: "Locked", className: "bg-primary/15 text-primary ring-primary/30" };
    case "conflict":
      return { Icon: AlertTriangle, label: "Conflict", className: "bg-destructive/15 text-destructive ring-destructive/30" };
    case "unverifiable":
      return { Icon: PencilLine, label: "Review", className: "bg-warning/15 text-warning ring-warning/30" };
    default:
      return { Icon: Sparkles, label: "Extracted", className: "bg-muted text-muted-foreground ring-border" };
  }
}

function sourceLabel(prov: FieldProvenance): string | undefined {
  if (!prov.source_doc_name) return undefined;
  return `${prov.source_doc_name}${prov.source_page ? ` · p.${prov.source_page}` : ""}`;
}

function humanizePath(path: string): string {
  const [, field = path] = path.split(".");
  return field
    .replace(/_/g, " ")
    .replace(/\b\w/g, (m) => m.toUpperCase())
    .replace(/\bIrr\b/, "IRR")
    .replace(/\bLtv\b/, "LTV")
    .replace(/\bNoi\b/, "NOI")
    .replace(/\bDscr\b/, "DSCR");
}

function formatRaw(value: unknown): string {
  if (value == null) return "-";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

function dateMs(value: string | null): number {
  if (!value) return 0;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? 0 : parsed.getTime();
}
