"use client";

import { motion } from "framer-motion";
import { Card } from "@/components/ui/card";
import { ScoreQualityBadge } from "@/components/deal-detail/score-quality-badge";
import { cn } from "@/lib/utils";
import type { DealScores, ReturnSchedule, ScoreCategory } from "@/lib/types";

const CATEGORIES: Array<{ key: keyof DealScores; label: string }> = [
  { key: "returns", label: "Returns" },
  { key: "market", label: "Market" },
  { key: "structure", label: "Structure" },
  { key: "risk", label: "Risk" },
  { key: "financials", label: "Financials" },
  { key: "underwriting", label: "Underwriting" },
  { key: "sponsor", label: "Sponsor" },
];

const CASH_ON_CASH_PATH = "target_returns.target_cash_on_cash";
const SCORE_INPUT_LABELS: Record<string, string> = {
  "target_returns.primary_strategy": "Primary investment strategy",
  "target_returns.target_irr": "Target IRR",
  "target_returns.target_equity_multiple": "Target equity multiple",
  [CASH_ON_CASH_PATH]: "Target cash-on-cash return",
  "market_location.market_rent_growth": "Market rent growth",
  "market_location.market_job_growth": "Market job growth",
  "market_location.market_vacancy_rate": "Market vacancy rate",
  "market_location.walk_score": "Walk Score",
  "deal_structure.preferred_return": "Preferred return",
  "deal_structure.fees_asset_mgmt": "Asset management fee",
  "deal_structure.fees_acquisition": "Acquisition fee",
  "deal_structure.gp_equity_coinvest_pct": "Sponsor co-investment",
  "target_returns.total_fee_drag": "Total impact of fees on returns",
  "deal_structure.ltv": "Loan-to-value ratio",
  "project_details.entitlement_status": "Entitlement status",
  "financial_projections.entry_cap_rate": "Entry cap rate",
  "financial_projections.exit_cap_rate": "Exit cap rate",
  "financial_projections.occupancy_assumption": "Modeled occupancy",
  "financial_projections.rent_growth_assumption": "Modeled rent growth",
  "financial_projections.operating_expense_ratio": "Operating expense ratio",
  "underwriting_checks.break_even_occupancy": "Break-even occupancy",
  "underwriting_checks.dscr": "Debt service coverage ratio",
  "underwriting_checks.yield_on_cost": "Yield on cost",
  "sponsor_evaluation.sponsor_full_cycle_deals": "Sponsor deals completed through exit",
};

function MissingScoreInputs({ paths, collapsed = false }: { paths: string[]; collapsed?: boolean }) {
  if (paths.length === 0) return null;

  const list = (
    <ul className="ml-4 mt-1 list-disc space-y-0.5 text-xs text-muted-foreground">
      {paths.map(path => {
        const field = (path.split(".").at(-1) ?? path).replaceAll("_", " ");
        return <li key={path}>{SCORE_INPUT_LABELS[path] ?? field.charAt(0).toUpperCase() + field.slice(1)}</li>;
      })}
    </ul>
  );

  if (!collapsed) return list;
  return (
    <details className="mt-2 text-xs text-muted-foreground">
      <summary className="cursor-pointer">Missing score inputs ({paths.length})</summary>
      {list}
    </details>
  );
}

function scoreNoteParts(notes: string): string[] {
  return notes
    .split(";")
    .map(cleanScoreNote)
    .filter(Boolean)
    .slice(0, 4);
}

function cleanScoreNote(note: string): string {
  let text = note.trim();
  if (!text) return "";

  text = text
    .replace(/^Primary strategy: long-term hold$/i, "Long-term hold primary")
    .replace(/^Primary strategy: sale$/i, "Sale case primary")
    .replace(/^sale case treated as optional\/hypothetical$/i, "Sale case optional")
    .replace(/^Sale-case equity multiple/i, "Optional sale multiple")
    .replace(/^Equity Multiple/i, "Equity multiple")
    .replace(/^Cash-on-Cash/i, "Cash-on-cash")
    .replace(/^Optional sale scenario shown separately \(/i, "Optional sale: ")
    .replace(/\)$/g, "")
    .replace(/\s*->\s*\d+(?:\.\d+)?\/10/g, "");

  return text;
}

/**
 * Horizontal bar chart of the 7 scoring categories. Each row shows weight,
 * score, and the scorer's notes. The bar grows in on mount for a bit of
 * dashboard-y polish.
 */
export function ScoreBreakdown({
  scores,
  returnSchedule,
  viewerMode = false,
}: {
  scores: Partial<DealScores>;
  returnSchedule?: ReturnSchedule | null;
  viewerMode?: boolean;
}) {
  if (!scores || Object.keys(scores).length === 0) {
    return (
      <Card elevated className="p-8 text-center">
        <div className="text-sm font-medium">No scores yet</div>
        <div className="text-xs text-muted-foreground mt-1">
          Category scores appear as their source-supported inputs become available.
        </div>
      </Card>
    );
  }

  const visibleOverall = typeof scores.overall === "number" ? scores.overall : scores.provisional_overall;
  const supportedCount = CATEGORIES.filter(category => typeof (scores[category.key] as ScoreCategory | undefined)?.score === "number").length;
  const hasReviewedReturnSchedule = returnSchedule?.rows.some(row => row.cash_on_cash_pct != null);

  return (
    <Card elevated className="p-6">
      <div className="flex items-start justify-between gap-4 mb-5">
        <div>
          <h3 className="text-base font-semibold tracking-tight">{viewerMode ? "Decision drivers" : "Score breakdown"}</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            {viewerMode
              ? "A simplified view of what is helping or hurting this deal."
              : `${supportedCount} of 7 categories have source-supported inputs.`}
          </p>
          {!viewerMode && (
            <div className="mt-2">
              <ScoreQualityBadge gate={scores.data_quality} />
            </div>
          )}
        </div>
        {typeof visibleOverall === "number" && (
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
              {typeof scores.overall === "number" ? "Overall" : "Partial composite"}
            </div>
            <div className="text-2xl font-semibold tabular-nums leading-none mt-1">
              {visibleOverall.toFixed(1)}
            </div>
          </div>
        )}
      </div>

      <div className="space-y-3.5">
        {CATEGORIES.map((c, i) => {
          const cat = scores[c.key] as ScoreCategory | undefined;
          if (!cat || typeof cat !== "object" || cat === null || !("score" in cat)) return null;
          const score = typeof cat.score === "number" ? Math.max(0, Math.min(10, cat.score)) : null;
          const missing = cat.missing_inputs ?? [];
          const notes = typeof cat.notes === "string" ? scoreNoteParts(cat.notes).slice(0, viewerMode ? 1 : 4) : [];

          if (score === null) {
            const showSchedule = c.key === "returns" && hasReviewedReturnSchedule;
            const missingInputs = showSchedule ? missing.filter(path => path !== CASH_ON_CASH_PATH) : missing;
            const context = notes.filter(note => !note.startsWith("Source-supported "));
            return (
              <div key={c.key} className="border-b border-border/50 pb-3 last:border-0">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{c.label}</span>
                  <span className="text-xs text-muted-foreground">{showSchedule ? "Reviewed schedule available" : "Needs source inputs"}</span>
                </div>
                {showSchedule && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    The reviewed schedule shows projected cash-on-cash by year. The Returns score requires a single primary return figure.
                  </p>
                )}
                {context.length > 0 && <p className="mt-1 text-xs text-muted-foreground">{context.join(" · ")}</p>}
                <MissingScoreInputs paths={missingInputs} />
              </div>
            );
          }
          const pct = score * 10;
          const barColor =
            score >= 8
              ? "bg-success"
              : score >= 6
                ? "bg-warning"
                : "bg-destructive";
          return (
            <div key={c.key}>
              <div className="flex items-center justify-between gap-2 mb-1.5">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{c.label}</span>
                  <span className="text-[10px] text-muted-foreground uppercase tracking-wider border border-border/70 rounded px-1.5 py-0.5">
                    {cat.weight}%
                  </span>
                </div>
                <span className="text-sm tabular-nums font-semibold">
                  {score.toFixed(1)}
                  <span className="text-muted-foreground text-xs font-normal">/10</span>
                </span>
              </div>
              <div className="relative h-1.5 rounded-full bg-muted overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${pct}%` }}
                  transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1], delay: 0.05 * i }}
                  className={cn("absolute inset-y-0 left-0 rounded-full", barColor)}
                />
              </div>
              {notes.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {notes.map((note) => (
                    <span
                      key={note}
                      className="rounded-full border border-border/70 bg-muted/45 px-2.5 py-1 text-[11px] font-medium leading-none text-muted-foreground"
                    >
                      {note}
                    </span>
                  ))}
                </div>
              )}
              <MissingScoreInputs paths={missing} collapsed />
            </div>
          );
        })}
      </div>
    </Card>
  );
}
