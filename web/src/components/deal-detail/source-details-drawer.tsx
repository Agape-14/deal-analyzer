"use client";

import * as React from "react";
import {
  AlertTriangle,
  Calculator,
  CheckCircle2,
  ExternalLink,
  FileText,
  HelpCircle,
  Lock,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogDescription, DialogSheet, DialogTitle } from "@/components/ui/dialog";
import { FieldReviewAction } from "@/components/deal-detail/field-review-action";
import { cn, fmtDate } from "@/lib/utils";
import type { FieldProvenance } from "@/lib/types";

export type SourceDetailsDrawerInput = {
  label: string;
  value: React.ReactNode;
  path?: string;
  provenance?: FieldProvenance;
};

export function SourceDetailsDrawer({
  open,
  onOpenChange,
  label,
  value,
  rawValue,
  path,
  provenance,
  issueTitle,
  issueDetail,
  issueWhy,
  inputs = [],
  dealId,
  showAdminAction,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  label: string;
  value: React.ReactNode;
  rawValue?: unknown;
  path?: string | null;
  provenance?: FieldProvenance;
  issueTitle?: string;
  issueDetail?: string;
  issueWhy?: string;
  inputs?: SourceDetailsDrawerInput[];
  dealId?: number;
  showAdminAction?: boolean;
}) {
  const citationHref = path ? sourceHref(path) : "#source-citations";
  const evidence = provenance ? sourceSearchText(provenance) : "";
  const source = metricSourceName(provenance);
  const location = metricSourceLocation(provenance);
  const status = statusStyle(String(provenance?.status ?? (provenance ? "extracted" : "missing")), Boolean(provenance?.conflict?.length));
  const confidence = typeof provenance?.confidence === "number" ? `${Math.round(provenance.confidence)}% confidence` : "Confidence not captured";
  const conflicts = Array.isArray(provenance?.conflict) ? provenance.conflict : [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogSheet className="sm:max-w-[620px]">
        <div className="border-b border-border/80 bg-card px-5 py-4 pr-12">
          <div className="flex items-start gap-3">
            <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary ring-1 ring-primary/25">
              <Search className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <div className="text-[10px] font-extrabold uppercase tracking-[0.16em] text-primary">Source pocket</div>
              <DialogTitle className="mt-1 text-lg font-extrabold">{issueTitle || label}</DialogTitle>
              <DialogDescription className="mt-1 leading-relaxed">
                Inspect the cited evidence, confirm the value, or correct it from the review row.
              </DialogDescription>
            </div>
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-5">
          {issueDetail || issueWhy ? (
            <section className="rounded-xl border border-warning/35 bg-warning/10 p-4">
              <div className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
                <div className="min-w-0">
                  <div className="text-sm font-extrabold text-foreground">{issueTitle || "Needs review"}</div>
                  {issueDetail ? <p className="mt-1 text-sm leading-relaxed text-foreground/85">{issueDetail}</p> : null}
                  {issueWhy ? <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{issueWhy}</p> : null}
                </div>
              </div>
            </section>
          ) : null}

          <section className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-xl border border-border/80 bg-background p-4">
              <div className="text-[10px] font-extrabold uppercase tracking-[0.13em] text-muted-foreground">Current value</div>
              <div className="mt-2 text-2xl font-extrabold tabular-nums text-foreground">{value}</div>
              {path ? <div className="mt-1 break-all text-xs text-muted-foreground">{path}</div> : null}
            </div>

            <div className="rounded-xl border border-border/80 bg-background p-4">
              <div className="text-[10px] font-extrabold uppercase tracking-[0.13em] text-muted-foreground">Verification status</div>
              <div className="mt-2 flex flex-wrap gap-2">
                <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-xs font-bold ring-1", status.className)}>
                  <status.Icon className="h-3.5 w-3.5" />
                  {status.label}
                </span>
                <span className="rounded-full border border-border bg-muted/40 px-2 py-1 text-xs font-semibold text-muted-foreground">
                  {confidence}
                </span>
              </div>
              {provenance?.verified_at ? (
                <div className="mt-2 text-xs text-muted-foreground">Verified {fmtDate(provenance.verified_at)}</div>
              ) : null}
              {provenance?.locked ? (
                <div className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-primary">
                  <Lock className="h-3 w-3" />
                  Locked by review
                </div>
              ) : null}
            </div>
          </section>

          <section className="rounded-xl border border-border/80 bg-background p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-[10px] font-extrabold uppercase tracking-[0.13em] text-muted-foreground">Cited source</div>
                <div className="mt-2 flex items-start gap-2 text-sm font-bold text-foreground">
                  <FileText className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 break-words">{source}</span>
                </div>
                {location ? <div className="mt-1 text-xs text-muted-foreground">{location}</div> : null}
              </div>
            </div>

            {evidence ? (
              <div className="mt-4 rounded-lg border border-primary/25 bg-primary/5 p-3">
                <div className="text-[10px] font-extrabold uppercase tracking-[0.13em] text-primary">Evidence to check</div>
                <p className="mt-1 text-sm leading-relaxed text-foreground">{evidence}</p>
              </div>
            ) : (
              <div className="mt-4 rounded-lg border border-border/80 bg-muted/25 p-3 text-sm leading-relaxed text-muted-foreground">
                No exact evidence note was captured. Use the citation row or document page link below to inspect the source context.
              </div>
            )}

            {conflicts.length ? (
              <div className="mt-4 rounded-lg border border-destructive/25 bg-destructive/5 p-3">
                <div className="text-[10px] font-extrabold uppercase tracking-[0.13em] text-destructive">Conflicting sources</div>
                <div className="mt-2 space-y-2">
                  {conflicts.slice(0, 4).map((conflict, index) => (
                    <div key={`${conflict.doc_id}-${index}`} className="rounded-md border border-border/70 bg-background px-2.5 py-2 text-xs">
                      <div className="font-semibold text-foreground">{conflict.doc_name}</div>
                      <div className="mt-0.5 text-muted-foreground">Value: {formatRaw(conflict.value)}</div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </section>

          {inputs.length ? (
            <section className="rounded-xl border border-border/80 bg-background p-4">
              <div className="text-[10px] font-extrabold uppercase tracking-[0.13em] text-muted-foreground">Related inputs</div>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                These are the values this review item depends on.
              </p>
              <div className="mt-3 grid gap-2">
                {inputs.map((input) => (
                  <div key={input.path || input.label} className="rounded-lg border border-border/70 bg-muted/20 px-3 py-2">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-xs font-bold text-foreground">{input.label}</div>
                        {input.path ? <div className="mt-0.5 break-all text-[11px] text-muted-foreground">{input.path}</div> : null}
                      </div>
                      <div className="shrink-0 text-right text-sm font-extrabold tabular-nums text-foreground">{input.value}</div>
                    </div>
                    {input.provenance?.source_doc_name ? (
                      <div className="mt-1 truncate text-[11px] text-muted-foreground">
                        Source: {metricSourceName(input.provenance)}
                        {input.provenance.source_page ? ` p.${input.provenance.source_page}` : ""}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {showAdminAction && dealId && path && isEditableScalar(rawValue) ? (
            <section className="rounded-xl border border-primary/25 bg-primary/5 p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="text-sm font-extrabold text-foreground">Admin action</div>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                    Confirm this value or save a corrected value from here.
                  </p>
                </div>
                <FieldReviewAction dealId={dealId} path={path} value={rawValue} provenance={provenance} />
              </div>
            </section>
          ) : null}
        </div>

        <div className="border-t border-border/80 bg-card p-4">
          <div className="grid gap-2 sm:grid-cols-2">
            {provenance?.source_doc_id ? (
              <Button variant="secondary" asChild>
                <a href={documentHref(provenance)} target="_blank" rel="noreferrer">
                  <ExternalLink className="h-3.5 w-3.5" />
                  Open document page
                </a>
              </Button>
            ) : null}
            <Button variant="outline" asChild>
              <a href={citationHref} onClick={() => onOpenChange(false)}>
                <ShieldCheck className="h-3.5 w-3.5" />
                Open citation row
              </a>
            </Button>
          </div>
        </div>
      </DialogSheet>
    </Dialog>
  );
}

function statusStyle(status: string, hasConflict: boolean) {
  if (hasConflict) {
    return {
      Icon: AlertTriangle,
      label: "Conflict",
      className: "bg-destructive/15 text-destructive ring-destructive/30",
    };
  }
  switch (status) {
    case "confirmed":
      return { Icon: CheckCircle2, label: "Verified", className: "bg-success/15 text-success ring-success/30" };
    case "wrong":
      return { Icon: AlertTriangle, label: "Needs review", className: "bg-destructive/15 text-destructive ring-destructive/30" };
    case "unverifiable":
      return { Icon: HelpCircle, label: "Unverifiable", className: "bg-muted text-muted-foreground ring-border" };
    case "calculated":
      return { Icon: Calculator, label: "Calculated", className: "bg-chart-3/15 text-[hsl(var(--chart-3))] ring-[hsl(var(--chart-3))]/30" };
    case "manual":
      return { Icon: Lock, label: "Manual", className: "bg-primary/15 text-primary ring-primary/30" };
    case "missing":
      return { Icon: AlertTriangle, label: "Missing", className: "bg-destructive/15 text-destructive ring-destructive/30" };
    default:
      return { Icon: Sparkles, label: "Extracted", className: "bg-warning/15 text-warning ring-warning/30" };
  }
}

function metricSourceName(provenance?: FieldProvenance): string {
  return provenance?.source_doc_name || provenance?.verification_source || "No source captured yet";
}

function metricSourceLocation(provenance?: FieldProvenance): string {
  if (!provenance) return "";
  const parts = [
    provenance.source_page ? `p.${provenance.source_page}` : "",
    provenance.source_sheet ? `sheet: ${provenance.source_sheet}` : "",
    provenance.source_cell ? `cell: ${provenance.source_cell}` : "",
    provenance.source_range ? `range: ${provenance.source_range}` : "",
  ].filter(Boolean);
  return parts.join(" - ");
}

function sourceSearchText(provenance: FieldProvenance): string {
  const raw =
    provenance.correction_source ||
    provenance.correction_note ||
    provenance.verification_source ||
    provenance.verification_note ||
    provenance.formula ||
    "";
  return String(raw)
    .replace(/^page\s+\d+\s*:\s*/i, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 240);
}

function documentHref(provenance: FieldProvenance): string {
  const hashParts: string[] = [];
  if (provenance.source_page) hashParts.push(`page=${provenance.source_page}`);
  if (provenance.source_sheet) hashParts.push(`sheet=${encodeURIComponent(provenance.source_sheet)}`);
  if (provenance.source_cell || provenance.source_range) {
    hashParts.push(`cell=${encodeURIComponent(String(provenance.source_cell || provenance.source_range))}`);
  }
  const search = sourceSearchText(provenance);
  if (search) hashParts.push(`search=${encodeURIComponent(search)}`);
  const hash = hashParts.length ? `#${hashParts.join("&")}` : "";
  return `/api/deals/documents/${provenance.source_doc_id}/file${hash}`;
}

function sourceHref(path: string): string {
  return `#source-citation-${path.replace(/[^a-zA-Z0-9_-]+/g, "-")}`;
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

function isEditableScalar(value: unknown): value is string | number | boolean | null {
  return value === null || ["string", "number", "boolean"].includes(typeof value);
}
