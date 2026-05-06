"use client";

import type { ReactNode } from "react";
import { AlertTriangle, Calculator, CheckCircle2, FileText, HelpCircle, Lock, Sparkles } from "lucide-react";
import { Card } from "@/components/ui/card";
import { FieldReviewAction } from "@/components/deal-detail/field-review-action";
import { cn, fmtDate, fmtMoney, fmtMultiple, fmtPct } from "@/lib/utils";
import type { DealDetail, FieldProvenance } from "@/lib/types";

type CitationFormat = "pct" | "multiple" | "money" | "years" | "integer";
type CitationField = { path: string; label: string; format: CitationFormat };

const CITATION_FIELDS: CitationField[] = [
  { path: "target_returns.target_irr", label: "Target IRR", format: "pct" },
  { path: "target_returns.target_equity_multiple", label: "Equity multiple", format: "multiple" },
  { path: "target_returns.target_cash_on_cash", label: "Cash-on-cash", format: "pct" },
  { path: "deal_structure.minimum_investment", label: "Minimum investment", format: "money" },
  { path: "deal_structure.total_project_cost", label: "Total project cost", format: "money" },
  { path: "deal_structure.total_equity_required", label: "Equity required", format: "money" },
  { path: "deal_structure.debt_amount", label: "Debt amount", format: "money" },
  { path: "deal_structure.ltv", label: "LTV", format: "pct" },
  { path: "deal_structure.hold_period_years", label: "Hold period", format: "years" },
  { path: "financial_projections.stabilized_noi", label: "Stabilized NOI", format: "money" },
  { path: "financial_projections.avg_rent_per_unit", label: "Average rent", format: "money" },
  { path: "financial_projections.occupancy_assumption", label: "Occupancy", format: "pct" },
  { path: "project_details.unit_count", label: "Unit count", format: "integer" },
];

type CitationMetrics = Record<string, unknown> & { _provenance?: Record<string, FieldProvenance> };

export function SourceCitations({ deal }: { deal: DealDetail }) {
  const metrics = (deal.metrics ?? {}) as CitationMetrics;
  const provenance = metrics._provenance ?? {};

  const rows = CITATION_FIELDS.map((field) => citationRow(metrics, provenance, field)).filter(
    (row) => row.value != null || row.prov,
  );

  if (rows.length === 0) return null;

  return (
    <Card elevated className="p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold tracking-tight">Source citations</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Key underwriting values with their source document, verification status, and correction notes.
          </p>
        </div>
        <div className="hidden sm:flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary ring-1 ring-primary/25">
          <FileText className="h-4 w-4" />
        </div>
      </div>

      <div className="mt-5 overflow-hidden rounded-lg border border-border/70">
        <div className="hidden md:grid grid-cols-[1.05fr_.75fr_1.25fr_.95fr] gap-4 bg-muted/35 px-4 py-2 text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
          <div>Metric</div>
          <div>Value</div>
          <div>Source</div>
          <div>Status</div>
        </div>
        <div className="divide-y divide-border/60">
          {rows.map(({ field, value, prov, note }) => (
            <CitationRow key={field.path} field={field} value={value} provenance={prov} dealId={deal.id} note={note} />
          ))}
        </div>
      </div>
    </Card>
  );
}

function citationRow(metrics: CitationMetrics, provenance: Record<string, FieldProvenance>, field: CitationField) {
  if (field.path === "target_returns.target_irr") {
    const netIrr = getMetricValue(metrics, "target_returns.net_irr");
    if (netIrr != null && netIrr !== "") {
      return {
        field: { ...field, path: "target_returns.net_irr" },
        value: netIrr,
        prov: provenance["target_returns.net_irr"] ?? provenance[field.path],
        note: "Using investor net IRR as the canonical Target IRR. Cash-on-cash remains separate below.",
      };
    }
  }
  const value = getMetricValue(metrics, field.path);
  return { field, value, prov: provenance[field.path], note: undefined };
}

function CitationRow({
  field,
  value,
  provenance,
  dealId,
  note,
}: {
  field: CitationField;
  value: unknown;
  provenance?: FieldProvenance;
  dealId: number;
  note?: string;
}) {
  const status = provenance?.status ?? (value == null ? "missing" : "extracted");
  const statusUi = statusStyle(status, Boolean(provenance?.conflict?.length));
  const correction = provenance?.previous_value !== undefined && provenance.previous_value !== null;

  return (
    <div className="grid grid-cols-1 md:grid-cols-[1.05fr_.75fr_1.25fr_.95fr] gap-3 md:gap-4 px-4 py-3 text-sm">
      <div>
        <div className="font-medium tracking-tight">{field.label}</div>
        <div className="mt-0.5 text-[11px] text-muted-foreground">{field.path}</div>
        {note && <div className="mt-1 text-[11px] leading-relaxed text-primary">{note}</div>}
      </div>

      <div>
        <MobileLabel>Value</MobileLabel>
        <div className="font-semibold tabular-nums">{formatMetric(value, field.format)}</div>
        {correction && field.path !== "target_returns.net_irr" && (
          <div className="mt-1 text-[11px] text-muted-foreground">
            corrected from <span className="line-through">{formatRaw(provenance?.previous_value)}</span>
          </div>
        )}
      </div>

      <div className="min-w-0">
        <MobileLabel>Source</MobileLabel>
        {provenance?.source_doc_name ? (
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 text-foreground">
              <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <span className="truncate">{provenance.source_doc_name}</span>
              {provenance.source_page && (
                <span className="shrink-0 text-muted-foreground">p.{provenance.source_page}</span>
              )}
            </div>
            {(provenance.verification_note || provenance.verification_source || provenance.correction_note || provenance.correction_source) && (
              <div className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                {provenance.correction_note || provenance.correction_source || provenance.verification_note || provenance.verification_source}
              </div>
            )}
          </div>
        ) : (
          <div className="text-muted-foreground">No source captured yet</div>
        )}
      </div>

      <div>
        <MobileLabel>Status</MobileLabel>
        <div className="flex flex-wrap items-center gap-1.5">
          <div
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[11px] font-medium ring-1",
              statusUi.className,
            )}
          >
            <statusUi.Icon className="h-3 w-3" />
            {statusUi.label}
          </div>
          <FieldReviewAction dealId={dealId} path={field.path} value={value} provenance={provenance} />
        </div>
        <div className="mt-1.5 space-y-0.5 text-[11px] text-muted-foreground">
          {provenance?.verified_at && <div>Verified {fmtDate(provenance.verified_at)}</div>}
          {typeof provenance?.confidence === "number" && <div>{provenance.confidence}% confidence</div>}
          {provenance?.locked && (
            <div className="inline-flex items-center gap-1 text-primary">
              <Lock className="h-3 w-3" /> locked
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function MobileLabel({ children }: { children: ReactNode }) {
  return <div className="mb-1 text-[10px] uppercase tracking-[0.12em] text-muted-foreground md:hidden">{children}</div>;
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
      return { Icon: AlertTriangle, label: "Corrected", className: "bg-destructive/15 text-destructive ring-destructive/30" };
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

function getMetricValue(metrics: CitationMetrics, path: string): unknown {
  let current: unknown = metrics;
  for (const part of path.split(".")) {
    if (!current || typeof current !== "object") return null;
    current = (current as Record<string, unknown>)[part];
  }
  return current;
}

function formatMetric(value: unknown, format: CitationFormat): string {
  if (value == null || value === "") return "-";
  const numeric = typeof value === "number" ? value : typeof value === "string" && !Number.isNaN(Number(value)) ? Number(value) : null;
  if (numeric == null) return String(value);

  switch (format) {
    case "pct":
      return fmtPct(numeric, 1);
    case "money":
      return fmtMoney(numeric);
    case "multiple":
      return fmtMultiple(numeric);
    case "years":
      return `${numeric} ${numeric === 1 ? "yr" : "yrs"}`;
    case "integer":
      return Math.round(numeric).toLocaleString();
    default:
      return String(value);
  }
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
