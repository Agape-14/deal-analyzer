/**
 * Preset definitions for the Compare tool.
 *
 * Each row references a dotted path into a DealDetail. Unknown paths resolve
 * to null and render as "—". The `direction` field drives winner/loser
 * highlighting: "higher" = bigger is better (IRR, multiple, score), "lower"
 * = smaller is better (LTV, fees, BEO), "none" = not comparable.
 *
 * To add your own metric row anywhere in the UI, just import ALL_ROWS and
 * pick what you want — or define a new preset and it'll show up in the
 * toolbar automatically.
 */

import type { DealDetail } from "@/lib/types";

export type Format =
  | "money"
  | "percent"
  | "multiple"
  | "number"
  | "integer"
  | "years"
  | "score"
  | "text";

export type Direction = "higher" | "lower" | "none";

export interface MetricRow {
  /** Unique key — used for checkbox state, stable ordering, url hashing. */
  key: string;
  /** Dotted path into a DealDetail. "metrics.deal_structure.ltv" etc. */
  path: string;
  label: string;
  format: Format;
  direction: Direction;
  /** Narrow group label so rows can be grouped inside a preset. */
  group: string;
  /** Extra short description that shows under the label. Optional. */
  hint?: string;
}

export interface Preset {
  key: string;
  label: string;
  description: string;
  rows: MetricRow[];
}

/* ---------- Single source of truth for every row we know about ---------- */

export const ALL_ROWS: MetricRow[] = [
  // Returns
  { key: "target_irr", path: "metrics.target_returns.target_irr", label: "Target IRR", format: "percent", direction: "higher", group: "Returns" },
  { key: "net_irr", path: "metrics.target_returns.net_irr", label: "Net IRR", format: "percent", direction: "higher", group: "Returns" },
  { key: "gross_irr", path: "metrics.target_returns.gross_irr", label: "Gross IRR", format: "percent", direction: "higher", group: "Returns" },
  { key: "equity_multiple", path: "metrics.target_returns.target_equity_multiple", label: "Equity Multiple", format: "multiple", direction: "higher", group: "Returns" },
  { key: "net_eq_multiple", path: "metrics.target_returns.net_equity_multiple", label: "Net Equity Multiple", format: "multiple", direction: "higher", group: "Returns" },
  { key: "cash_on_cash", path: "metrics.target_returns.target_cash_on_cash", label: "Cash-on-Cash", format: "percent", direction: "higher", group: "Returns" },
  { key: "distribution_yield", path: "metrics.target_returns.distribution_yield", label: "Distribution Yield", format: "percent", direction: "higher", group: "Returns" },
  { key: "projected_profit", path: "metrics.target_returns.projected_profit", label: "Projected Profit", format: "money", direction: "higher", group: "Returns" },

  // Structure & leverage
  { key: "ltv", path: "metrics.deal_structure.ltv", label: "LTV", format: "percent", direction: "lower", group: "Structure & leverage", hint: "Lower = more conservative" },
  { key: "debt_amount", path: "metrics.deal_structure.debt_amount", label: "Debt Amount", format: "money", direction: "none", group: "Structure & leverage" },
  { key: "interest_rate", path: "metrics.deal_structure.interest_rate", label: "Interest Rate", format: "percent", direction: "lower", group: "Structure & leverage" },
  { key: "preferred_return", path: "metrics.deal_structure.preferred_return", label: "Preferred Return", format: "percent", direction: "higher", group: "Structure & leverage" },
  { key: "gp_coinvest_pct", path: "metrics.deal_structure.gp_equity_coinvest_pct", label: "GP Co-invest", format: "percent", direction: "higher", group: "Structure & leverage", hint: "Skin in the game" },
  { key: "hold_period_years", path: "metrics.deal_structure.hold_period_years", label: "Hold Period", format: "years", direction: "none", group: "Structure & leverage" },
  { key: "investment_class", path: "metrics.deal_structure.investment_class", label: "Class", format: "text", direction: "none", group: "Structure & leverage" },
  { key: "min_investment", path: "minimum_investment", label: "Min Investment", format: "money", direction: "lower", group: "Structure & leverage", hint: "Lower = more accessible" },

  // Fees (all lower = better)
  { key: "fees_asset_mgmt", path: "metrics.deal_structure.fees_asset_mgmt", label: "Asset Mgmt Fee", format: "percent", direction: "lower", group: "Fees" },
  { key: "fees_acquisition", path: "metrics.deal_structure.fees_acquisition", label: "Acquisition Fee", format: "percent", direction: "lower", group: "Fees" },
  { key: "fees_disposition", path: "metrics.deal_structure.fees_disposition", label: "Disposition Fee", format: "percent", direction: "lower", group: "Fees" },
  { key: "fees_dev", path: "metrics.deal_structure.fees_dev_fee", label: "Developer Fee", format: "percent", direction: "lower", group: "Fees" },

  // Financials
  { key: "stabilized_noi", path: "metrics.financial_projections.stabilized_noi", label: "Stabilized NOI", format: "money", direction: "higher", group: "Financials" },
  { key: "entry_cap_rate", path: "metrics.financial_projections.entry_cap_rate", label: "Entry Cap Rate", format: "percent", direction: "higher", group: "Financials" },
  { key: "exit_cap_rate", path: "metrics.financial_projections.exit_cap_rate", label: "Exit Cap Rate", format: "percent", direction: "none", group: "Financials", hint: "Higher = more conservative underwriting" },
  { key: "rent_growth", path: "metrics.financial_projections.rent_growth_assumption", label: "Rent Growth", format: "percent", direction: "none", group: "Financials" },
  { key: "occupancy", path: "metrics.financial_projections.occupancy_assumption", label: "Occupancy Assumption", format: "percent", direction: "none", group: "Financials" },
  { key: "expense_ratio", path: "metrics.financial_projections.operating_expense_ratio", label: "OpEx Ratio", format: "percent", direction: "lower", group: "Financials" },

  // Market
  { key: "city", path: "city", label: "City", format: "text", direction: "none", group: "Market" },
  { key: "state", path: "state", label: "State", format: "text", direction: "none", group: "Market" },
  { key: "submarket", path: "metrics.market_location.submarket", label: "Submarket", format: "text", direction: "none", group: "Market" },
  { key: "market_job_growth", path: "metrics.market_location.market_job_growth", label: "Job Growth", format: "percent", direction: "higher", group: "Market" },
  { key: "market_rent_growth", path: "metrics.market_location.market_rent_growth", label: "Market Rent Growth", format: "percent", direction: "higher", group: "Market" },
  { key: "market_vacancy", path: "metrics.market_location.market_vacancy_rate", label: "Market Vacancy", format: "percent", direction: "lower", group: "Market" },
  { key: "walk_score", path: "metrics.market_location.walk_score", label: "Walk Score", format: "integer", direction: "higher", group: "Market" },

  // Project
  { key: "unit_count", path: "metrics.project_details.unit_count", label: "Units", format: "integer", direction: "none", group: "Project" },
  { key: "total_sqft", path: "metrics.project_details.total_sqft", label: "Total Sqft", format: "integer", direction: "none", group: "Project" },
  { key: "construction_type", path: "metrics.project_details.construction_type", label: "Construction", format: "text", direction: "none", group: "Project" },
  { key: "entitlement_status", path: "metrics.project_details.entitlement_status", label: "Entitlement", format: "text", direction: "none", group: "Project" },
  { key: "total_project_cost", path: "metrics.deal_structure.total_project_cost", label: "Total Project Cost", format: "money", direction: "none", group: "Project" },
  { key: "total_equity_required", path: "metrics.deal_structure.total_equity_required", label: "Total Equity Required", format: "money", direction: "none", group: "Project" },

  // Risk & underwriting
  { key: "beo", path: "metrics.underwriting_checks.break_even_occupancy", label: "Break-even Occupancy", format: "percent", direction: "lower", group: "Risk & underwriting", hint: "Lower = more cushion" },
  { key: "dscr", path: "metrics.underwriting_checks.dscr", label: "DSCR", format: "number", direction: "higher", group: "Risk & underwriting" },
  { key: "yoc", path: "metrics.underwriting_checks.yield_on_cost", label: "Yield on Cost", format: "percent", direction: "higher", group: "Risk & underwriting" },
  { key: "market_risk_score", path: "metrics.risk_assessment.market_risk_score", label: "Market Risk", format: "score", direction: "higher", group: "Risk & underwriting", hint: "10 = lowest risk" },
  { key: "execution_risk_score", path: "metrics.risk_assessment.execution_risk_score", label: "Execution Risk", format: "score", direction: "higher", group: "Risk & underwriting" },
  { key: "financial_risk_score", path: "metrics.risk_assessment.financial_risk_score", label: "Financial Risk", format: "score", direction: "higher", group: "Risk & underwriting" },
  { key: "entitlement_risk_score", path: "metrics.risk_assessment.entitlement_risk_score", label: "Entitlement Risk", format: "score", direction: "higher", group: "Risk & underwriting" },
  { key: "overall_risk_score", path: "metrics.risk_assessment.overall_risk_score", label: "Overall Risk", format: "score", direction: "higher", group: "Risk & underwriting" },

  // Sponsor
  { key: "sponsor_full_cycle", path: "metrics.sponsor_evaluation.sponsor_full_cycle_deals", label: "Full-Cycle Deals", format: "integer", direction: "higher", group: "Sponsor" },
  { key: "sponsor_alignment_score", path: "metrics.sponsor_evaluation.alignment_score", label: "Alignment Score", format: "score", direction: "higher", group: "Sponsor" },
  { key: "developer_name", path: "developer_name", label: "Sponsor", format: "text", direction: "none", group: "Sponsor" },

  // Scores (analyst composite)
  { key: "overall_score", path: "overall_score", label: "Overall Score", format: "score", direction: "higher", group: "Analyst scores" },
  { key: "score_returns", path: "scores.returns.score", label: "Returns Score", format: "score", direction: "higher", group: "Analyst scores" },
  { key: "score_market", path: "scores.market.score", label: "Market Score", format: "score", direction: "higher", group: "Analyst scores" },
  { key: "score_structure", path: "scores.structure.score", label: "Structure Score", format: "score", direction: "higher", group: "Analyst scores" },
  { key: "score_risk", path: "scores.risk.score", label: "Risk Score", format: "score", direction: "higher", group: "Analyst scores" },
  { key: "score_financials", path: "scores.financials.score", label: "Financials Score", format: "score", direction: "higher", group: "Analyst scores" },
  { key: "score_underwriting", path: "scores.underwriting.score", label: "Underwriting Score", format: "score", direction: "higher", group: "Analyst scores" },
  { key: "score_sponsor", path: "scores.sponsor.score", label: "Sponsor Score", format: "score", direction: "higher", group: "Analyst scores" },
];

const rowsByKey = new Map(ALL_ROWS.map((r) => [r.key, r]));
export function getRow(key: string): MetricRow | undefined {
  return rowsByKey.get(key);
}

function rows(keys: string[]): MetricRow[] {
  return keys.map((k) => rowsByKey.get(k)).filter((r): r is MetricRow => Boolean(r));
}

export const PRESETS: Preset[] = [
  {
    key: "exec",
    label: "Executive summary",
    description: "Top-line return profile + sponsor at a glance.",
    rows: rows([
      "overall_score",
      "target_irr",
      "equity_multiple",
      "cash_on_cash",
      "hold_period_years",
      "min_investment",
      "preferred_return",
      "developer_name",
    ]),
  },
  {
    key: "returns",
    label: "Returns",
    description: "Every return metric side-by-side — gross, net, yield, CoC.",
    rows: rows([
      "target_irr",
      "net_irr",
      "gross_irr",
      "equity_multiple",
      "net_eq_multiple",
      "cash_on_cash",
      "distribution_yield",
      "projected_profit",
    ]),
  },
  {
    key: "structure",
    label: "Leverage & structure",
    description: "Capital stack, leverage, pref, and fees.",
    rows: rows([
      "ltv",
      "debt_amount",
      "interest_rate",
      "preferred_return",
      "gp_coinvest_pct",
      "hold_period_years",
      "investment_class",
      "min_investment",
      "fees_asset_mgmt",
      "fees_acquisition",
      "fees_disposition",
      "fees_dev",
    ]),
  },
  {
    key: "risk",
    label: "Risk profile",
    description: "Downside indicators and risk-category scores.",
    rows: rows([
      "beo",
      "dscr",
      "yoc",
      "ltv",
      "exit_cap_rate",
      "market_risk_score",
      "execution_risk_score",
      "financial_risk_score",
      "entitlement_risk_score",
      "overall_risk_score",
      "score_risk",
    ]),
  },
  {
    key: "market",
    label: "Market & location",
    description: "Geography, demographics, and market fundamentals.",
    rows: rows([
      "city",
      "state",
      "submarket",
      "market_job_growth",
      "market_rent_growth",
      "market_vacancy",
      "walk_score",
      "score_market",
    ]),
  },
  {
    key: "sponsor",
    label: "Sponsor quality",
    description: "Track record, alignment, and analyst sponsor score.",
    rows: rows([
      "developer_name",
      "sponsor_full_cycle",
      "sponsor_alignment_score",
      "gp_coinvest_pct",
      "score_sponsor",
    ]),
  },
  {
    key: "underwriting",
    label: "Underwriting conservatism",
    description: "Does the proforma hold up? Caps, rents, reserves.",
    rows: rows([
      "entry_cap_rate",
      "exit_cap_rate",
      "rent_growth",
      "occupancy",
      "expense_ratio",
      "beo",
      "dscr",
      "yoc",
      "score_underwriting",
    ]),
  },
  {
    key: "all",
    label: "All metrics",
    description: "Every row we know about, grouped.",
    rows: ALL_ROWS,
  },
];

/* --- tiny helpers for retrieving / formatting values (shared) --- */

export function getValueAt(deal: DealDetail, path: string): unknown {
  const parts = path.split(".");
  let cur: unknown = deal;
  for (const p of parts) {
    if (cur == null || typeof cur !== "object") return null;
    cur = (cur as Record<string, unknown>)[p];
  }
  return cur;
}
