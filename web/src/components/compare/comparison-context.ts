import type { AnalysisFact, DealDetail } from "@/lib/types";
import type { MetricRow } from "./presets";

export function rowFact(deal: DealDetail, row: MetricRow): AnalysisFact | undefined {
  const canonical = "metrics._canonical_returns.";
  let path = row.path.replace(/^metrics\./, "");
  if (row.path.startsWith(canonical)) {
    const key = row.path.slice(canonical.length) + "_path";
    path = (deal.analysis?.returns as unknown as Record<string, string | null>)?.[key] ?? "";
  }
  if (row.path === "minimum_investment") path = "deal_structure.minimum_investment";
  return deal.analysis?.facts[path];
}

export function returnContext(fact?: AnalysisFact): string {
  if (!fact) return "Return context unavailable";
  const identity = fact.identity;
  return [identity.scenario === "unspecified" ? "Scenario unspecified" : identity.scenario.replaceAll("_", " "),
    identity.investor_class === "unspecified" ? "Class unspecified" : identity.investor_class,
    identity.basis === "unspecified" ? "Basis unspecified" : identity.basis,
    identity.period === "unspecified" ? "Period unspecified" : identity.period].join(" · ");
}

export function isReturnMetric(row: MetricRow): boolean {
  return row.group === "Returns" || row.key === "preferred_return";
}

export function isScopedOperatingMetric(row: MetricRow): boolean {
  return ["ltv", "loan_to_cost", "stabilized_noi", "untrended_noi"].includes(row.key);
}

export function scoreCategory(row: MetricRow): string | null {
  if (row.path === "overall_score") return "overall";
  return /^scores\.([a-z]+)\.score$/.exec(row.path)?.[1] ?? null;
}

export function scoreComparisonBasis(deal: DealDetail, row: MetricRow) {
  const category = scoreCategory(row);
  return category ? deal.scores?.comparison_basis?.[category] : undefined;
}

export function compatibleRow(deals: DealDetail[], row: MetricRow): boolean {
  const category = scoreCategory(row);
  if (category) {
    const scored = deals.filter(deal => {
      if (category === "overall") return typeof deal.overall_score === "number";
      const scores = deal.scores as Partial<Record<string, {score: number | null}>> | undefined;
      return typeof scores?.[category]?.score === "number";
    });
    const signatures = scored.map(deal => scoreComparisonBasis(deal, row)?.signature);
    return signatures.length >= 2 && !!signatures[0] && signatures.every(signature => signature === signatures[0]);
  }
  if (!isReturnMetric(row) && !isScopedOperatingMetric(row)) return true;
  const facts = deals.map(deal => rowFact(deal, row)).filter((fact): fact is AnalysisFact => !!fact && fact.value != null && ["manual", "checked", "calculated"].includes(fact.state));
  if (facts.length < 2) return false;
  const keys = isReturnMetric(row) ? ["unit", "scenario", "investor_class", "basis", "period"] as const
    : row.key === "ltv" || row.key === "loan_to_cost" ? ["unit", "debt_phase", "period"] as const
      : ["unit", "basis", "period"] as const;
  if (facts.some(fact => keys.some(key => !fact.identity[key] || ["unspecified", "unknown"].includes(fact.identity[key])))) return false;
  return facts.every(fact => keys.every(key => fact.identity[key].trim().toLowerCase() === facts[0].identity[key].trim().toLowerCase()) && fact.identity.debt_phase === facts[0].identity.debt_phase && fact.identity.currency === facts[0].identity.currency);
}
