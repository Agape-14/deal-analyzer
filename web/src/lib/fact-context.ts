import type { AnalysisFact } from "./types";

export function operatingFactContext(fact?: AnalysisFact): string {
  if (!fact) return "";
  const { basis, period, debt_phase } = fact.identity;
  return [debt_phase, basis, period].filter(value => value && value !== "unspecified").join(" · ");
}
