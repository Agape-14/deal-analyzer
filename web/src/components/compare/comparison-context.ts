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

export function compatibleRow(deals: DealDetail[], row: MetricRow): boolean {
  if (row.group !== "Returns") return true;
  const facts = deals.map(deal => rowFact(deal, row)).filter((fact): fact is AnalysisFact => !!fact && fact.value != null && ["manual", "checked", "calculated"].includes(fact.state));
  if (facts.length < 2) return false;
  const keys = ["unit", "scenario", "investor_class", "basis", "period"] as const;
  if (facts.some(fact => keys.some(key => !fact.identity[key] || ["unspecified", "unknown"].includes(fact.identity[key])))) return false;
  return facts.every(fact => keys.every(key => fact.identity[key].trim().toLowerCase() === facts[0].identity[key].trim().toLowerCase()) && fact.identity.debt_phase === facts[0].identity.debt_phase && fact.identity.currency === facts[0].identity.currency);
}
