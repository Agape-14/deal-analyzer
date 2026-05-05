"use client";

import { AlertTriangle, CheckCircle2, FileCheck2, FileQuestion, ShieldAlert } from "lucide-react";
import { Card } from "@/components/ui/card";
import type { DealDetail } from "@/lib/types";

const REQUIRED_EVIDENCE = [
  {
    label: "Offering memo",
    detail: "Core narrative, deal terms, sponsor, and return targets.",
    test: (deal: DealDetail) => hasDocType(deal, "offering_memo"),
  },
  {
    label: "Financial model or proforma",
    detail: "NOI, rent, expense, debt, and sale assumptions.",
    test: (deal: DealDetail) => hasDocType(deal, "proforma") || hasAny(deal.metrics?.financial_projections),
  },
  {
    label: "Sources and uses / construction budget",
    detail: "Project cost, equity required, and per-unit cost support.",
    test: (deal: DealDetail) =>
      hasAny(deal.metrics?.construction_costs, ["total_project_cost_per_unit", "hard_costs_per_unit", "land_cost_per_unit"]) ||
      hasAny(deal.metrics?.deal_structure, ["total_project_cost", "total_equity_required"]),
  },
  {
    label: "Debt terms",
    detail: "Loan amount, interest rate, LTV, DSCR, and debt service support.",
    test: (deal: DealDetail) =>
      hasAny(deal.metrics?.deal_structure, ["ltv", "interest_rate"]) &&
      hasAny(deal.metrics?.underwriting_checks, ["dscr", "break_even_occupancy"]),
  },
  {
    label: "Market support",
    detail: "Rent growth, vacancy, comps, demographics, or third-party market evidence.",
    test: (deal: DealDetail) => hasDocType(deal, "market_study") || hasAny(deal.metrics?.market_location),
  },
  {
    label: "Sponsor support",
    detail: "Sponsor name, track record, defaults, and GP cash-at-risk evidence.",
    test: (deal: DealDetail) => hasAny(deal.metrics?.sponsor_evaluation) || hasAny(deal.metrics?.deal_structure, ["gp_cash_at_risk", "gp_equity_coinvest_pct"]),
  },
];

export function UploadCompleteness({ deal }: { deal: DealDetail }) {
  const checks = REQUIRED_EVIDENCE.map((item) => ({ ...item, present: item.test(deal) }));
  const present = checks.filter((item) => item.present).length;
  const missing = checks.length - present;
  const weakDocs = (deal.documents ?? []).filter((doc) => (doc.extraction_quality?.quality_score ?? 100) < 80);
  const score = Math.round((present / checks.length) * 100);
  const status = missing === 0 && weakDocs.length === 0 ? "complete" : missing >= 3 ? "thin" : "review";

  return (
    <Card elevated className="p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex items-start gap-3">
          <div className={statusIconClass(status)}>
            {status === "complete" ? <FileCheck2 className="h-5 w-5" /> : <ShieldAlert className="h-5 w-5" />}
          </div>
          <div>
            <div className="text-base font-semibold tracking-tight">Upload completeness</div>
            <p className="mt-1 text-sm text-muted-foreground">
              {present} of {checks.length} evidence groups found. Scores are strongest when every major assumption has a source document.
            </p>
          </div>
        </div>
        <div className="rounded-lg border border-border/70 bg-secondary/30 px-3 py-2 text-right">
          <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">Package score</div>
          <div className="mt-1 text-lg font-semibold tabular-nums">{score}%</div>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
        {checks.map((item) => (
          <div key={item.label} className="rounded-lg border border-border/60 bg-background/35 p-3">
            <div className="flex items-center gap-2 text-sm font-medium">
              {item.present ? (
                <CheckCircle2 className="h-4 w-4 text-success" />
              ) : (
                <FileQuestion className="h-4 w-4 text-warning" />
              )}
              {item.label}
            </div>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">{item.present ? item.detail : `Missing or not identified. ${item.detail}`}</p>
          </div>
        ))}
      </div>

      {weakDocs.length > 0 && (
        <div className="mt-4 rounded-lg border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
          <div className="flex items-center gap-2 font-medium">
            <AlertTriangle className="h-4 w-4" />
            Low extraction quality
          </div>
          <p className="mt-1 text-xs leading-5 text-warning/90">
            {weakDocs.map((doc) => doc.filename).join(", ")} should be reviewed because OCR/text quality is below 80%.
          </p>
        </div>
      )}
    </Card>
  );
}

function hasDocType(deal: DealDetail, docType: string): boolean {
  return (deal.documents ?? []).some((doc) => doc.doc_type === docType);
}

function hasAny(section?: Record<string, unknown>, keys?: string[]): boolean {
  if (!section) return false;
  const values = keys ? keys.map((key) => section[key]) : Object.values(section);
  return values.some((value) => value !== null && value !== undefined && value !== "");
}

function statusIconClass(status: "complete" | "review" | "thin"): string {
  if (status === "complete") return "grid h-11 w-11 place-items-center rounded-lg bg-success/15 text-success ring-1 ring-success/30";
  if (status === "thin") return "grid h-11 w-11 place-items-center rounded-lg bg-destructive/15 text-destructive ring-1 ring-destructive/30";
  return "grid h-11 w-11 place-items-center rounded-lg bg-warning/15 text-warning ring-1 ring-warning/30";
}
