"use client";

import * as React from "react";
import type { ReactNode } from "react";
import { AlertTriangle, Calculator, CheckCircle2, ExternalLink, FileText, HelpCircle, Lock, Sparkles } from "lucide-react";
import { Card } from "@/components/ui/card";
import { FieldReviewAction } from "@/components/deal-detail/field-review-action";
import { cn, fmtDate, fmtMoney, fmtMultiple, fmtPct } from "@/lib/utils";
import type { DealDetail, FieldProvenance } from "@/lib/types";

type CitationFormat = "pct" | "multiple" | "money" | "years" | "integer";
type CitationField = { path: string; label: string; format: CitationFormat };

const CITATION_FIELDS: CitationField[] = [
  { path: "target_returns.target_irr", label: "Target IRR", format: "pct" },
  { path: "target_returns.net_irr", label: "Net IRR", format: "pct" },
  { path: "target_returns.target_equity_multiple", label: "Equity multiple", format: "multiple" },
  { path: "target_returns.net_equity_multiple", label: "Net equity multiple", format: "multiple" },
  { path: "target_returns.target_cash_on_cash", label: "Cash-on-cash", format: "pct" },
  { path: "target_returns.distribution_yield", label: "Distribution yield", format: "pct" },
  { path: "deal_structure.minimum_investment", label: "Minimum investment", format: "money" },
  { path: "deal_structure.total_project_cost", label: "Total project cost", format: "money" },
  { path: "deal_structure.total_equity_required", label: "Equity required", format: "money" },
  { path: "deal_structure.preferred_equity_amount", label: "Pref equity", format: "money" },
  { path: "deal_structure.debt_amount", label: "Debt amount", format: "money" },
  { path: "deal_structure.interest_rate", label: "Interest rate", format: "pct" },
  { path: "deal_structure.ltv", label: "LTV", format: "pct" },
  { path: "deal_structure.hold_period_years", label: "Hold period", format: "years" },
  { path: "financial_projections.stabilized_noi", label: "Stabilized NOI", format: "money" },
  { path: "financial_projections.avg_rent_per_unit", label: "Average rent", format: "money" },
  { path: "financial_projections.occupancy_assumption", label: "Occupancy", format: "pct" },
  { path: "underwriting_checks.dscr", label: "DSCR", format: "multiple" },
  { path: "construction_costs.hard_costs", label: "Hard costs", format: "money" },
  { path: "construction_costs.hard_costs_total", label: "Hard costs total", format: "money" },
  { path: "construction_costs.soft_costs", label: "Soft costs", format: "money" },
  { path: "construction_costs.soft_costs_total", label: "Soft costs total", format: "money" },
  { path: "construction_costs.land_cost", label: "Land", format: "money" },
  { path: "construction_costs.land_cost_total", label: "Land total", format: "money" },
  { path: "construction_costs.contingency", label: "Contingency", format: "money" },
  { path: "construction_costs.contingency_total", label: "Contingency total", format: "money" },
  { path: "project_details.unit_count", label: "Unit count", format: "integer" },
];

type CitationMetrics = Record<string, unknown> & { _provenance?: Record<string, FieldProvenance> };

export function SourceCitations({ deal }: { deal: DealDetail }) {
  const metrics = (deal.metrics ?? {}) as CitationMetrics;
  const provenance = metrics._provenance ?? {};
  const [activeCitation, setActiveCitation] = React.useState("");

  React.useEffect(() => {
    function updateActiveCitation() {
      setActiveCitation(window.location.hash.replace("#", ""));
    }
    updateActiveCitation();
    window.addEventListener("hashchange", updateActiveCitation);
    return () => window.removeEventListener("hashchange", updateActiveCitation);
  }, []);

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

      <div className="mt-5 overflow-visible rounded-lg border border-border/70">
        <div className="hidden md:grid grid-cols-[1.05fr_.75fr_1.25fr_.95fr] gap-4 rounded-t-lg bg-muted/35 px-4 py-2 text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
          <div>Metric</div>
          <div>Value</div>
          <div>Source</div>
          <div>Status</div>
        </div>
        <div className="divide-y divide-border/60">
          {rows.map(({ field, value, prov, note, anchorPath }) => (
            <CitationRow
              key={`${anchorPath}:${field.path}`}
              field={field}
              value={value}
              provenance={prov}
              dealId={deal.id}
              note={note}
              anchorPath={anchorPath}
              activeCitation={activeCitation}
            />
          ))}
        </div>
      </div>
    </Card>
  );
}

function citationRow(metrics: CitationMetrics, provenance: Record<string, FieldProvenance>, field: CitationField) {
  if (field.path === "target_returns.target_irr") {
    const canonical = pickCanonicalReturnMetric(metrics, provenance, ["target_returns.target_irr", "target_returns.net_irr"]);
    if (canonical) {
      return {
        field: { ...field, path: canonical.path },
        value: canonical.value,
        prov: canonical.prov,
        anchorPath: field.path,
        note: canonical.path === "target_returns.target_irr"
          ? "Using Target IRR as the headline return metric. Net IRR and cash-on-cash remain separate checks."
          : "Target IRR is missing, so investor net IRR is being used as the fallback headline return.",
      };
    }
  }
  const value = getMetricValue(metrics, field.path);
  return { field, value, prov: provenance[field.path], note: undefined, anchorPath: field.path };
}

function CitationRow({
  field,
  value,
  provenance,
  dealId,
  note,
  anchorPath,
  activeCitation,
}: {
  field: CitationField;
  value: unknown;
  provenance?: FieldProvenance;
  dealId: number;
  note?: string;
  anchorPath: string;
  activeCitation: string;
}) {
  const status = provenance?.status ?? (value == null ? "missing" : "extracted");
  const statusUi = statusStyle(status, Boolean(provenance?.conflict?.length));
  const correction = provenance?.previous_value !== undefined && provenance.previous_value !== null;
  const rowId = sourceCitationId(anchorPath);
  const isActive = activeCitation === rowId;

  return (
    <div
      id={rowId}
      className={cn(
        "scroll-mt-28 grid grid-cols-1 gap-3 px-4 py-3 text-sm transition-all target:bg-primary/10 target:ring-2 target:ring-primary/45 md:grid-cols-[1.05fr_.75fr_1.25fr_.95fr] md:gap-4",
        isActive && "bg-primary/10 ring-2 ring-primary/45",
      )}
    >
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="font-medium tracking-tight">{field.label}</div>
          {isActive && (
            <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[10px] font-medium text-primary ring-1 ring-primary/30">
              Reviewing this source
            </span>
          )}
        </div>
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
            {provenance.source_doc_id && (
              <a
                href={documentHref(provenance)}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-border/70 bg-background px-2 py-1 text-[11px] font-medium text-foreground transition-colors hover:bg-muted"
              >
                <ExternalLink className="h-3 w-3" />
                Open document page
              </a>
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

function pickCanonicalReturnMetric(
  metrics: CitationMetrics,
  provenance: Record<string, FieldProvenance>,
  paths: string[],
): { path: string; value: unknown; prov?: FieldProvenance } | null {
  const candidates = paths
    .map((path) => ({ path, value: getMetricValue(metrics, path), prov: provenance[path] }))
    .filter((candidate) => candidate.value != null && candidate.value !== "");

  if (candidates.length === 0) return null;
  const clean = candidates.filter((candidate) => !isBadSource(candidate.prov));
  const reviewed = clean.find((candidate) => candidate.prov?.locked || ["manual", "confirmed", "calculated"].includes(String(candidate.prov?.status ?? "")));
  return reviewed ?? clean[0] ?? candidates[0];
}

function isBadSource(provenance?: FieldProvenance): boolean {
  if (!provenance) return false;
  const status = String(provenance.status ?? "").toLowerCase();
  const conflictCount = Array.isArray(provenance.conflict) ? provenance.conflict.length : 0;
  return conflictCount > 1 || ["wrong", "missing", "unverifiable", "stale"].includes(status);
}

function sourceCitationId(path: string): string {
  return `source-citation-${path.replace(/[^a-zA-Z0-9_-]+/g, "-")}`;
}

function documentHref(provenance: FieldProvenance): string {
  const page = provenance.source_page ? `#page=${provenance.source_page}` : "";
  return `/api/deals/documents/${provenance.source_doc_id}/file${page}`;
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
