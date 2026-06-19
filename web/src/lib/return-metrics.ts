import type { DealDetail, FieldProvenance } from "@/lib/types";

type Metrics = NonNullable<DealDetail["metrics"]>;
type ProvenanceMap = Record<string, FieldProvenance | undefined>;
type ReturnMetricDeal = {
  metrics?: Partial<Metrics> | null;
  target_irr?: unknown;
  target_equity_multiple?: unknown;
  target_cash_on_cash?: unknown;
};

const TRUE_IRR_PATHS = ["target_returns.target_irr", "target_returns.net_irr"];
const CASH_YIELD_PATHS = [
  "target_returns.target_cash_on_cash",
  "target_returns.distribution_yield",
  "target_returns.hold_scenario.cash_on_cash_return",
  "target_returns.hold_scenario.distribution_yield",
];
const MULTIPLE_PATHS = ["target_returns.target_equity_multiple", "target_returns.net_equity_multiple"];

export type HeadlineReturnMetrics = {
  headlineIrr: number | null;
  headlineCashOnCash: number | null;
  headlineMultiple: number | null;
  primaryReturnLabel: "Target IRR" | "Cash-on-Cash";
  primaryReturnValue: number | null;
};

export function getHeadlineReturnMetrics(
  deal: ReturnMetricDeal,
): HeadlineReturnMetrics {
  const metrics = (deal.metrics ?? {}) as Metrics;
  const canonical = metrics._canonical_returns;
  const provenance = (metrics._provenance ?? {}) as ProvenanceMap;
  const isHoldStrategy = isHoldReturnStrategy(canonical?.primary_strategy);

  const fallbackIrr = isHoldStrategy
    ? null
    : pickTrustedNumber(metrics, provenance, TRUE_IRR_PATHS) ?? asNumber(deal.target_irr);
  const headlineIrr = asNumber(canonical?.target_irr) ?? fallbackIrr;
  const headlineCashOnCash =
    asNumber(canonical?.cash_on_cash) ??
    pickTrustedNumber(metrics, provenance, CASH_YIELD_PATHS) ??
    asNumber(deal.target_cash_on_cash);
  const headlineMultiple =
    asNumber(canonical?.target_equity_multiple) ??
    pickTrustedNumber(metrics, provenance, MULTIPLE_PATHS) ??
    asNumber(deal.target_equity_multiple);

  const primaryReturnLabel = headlineIrr !== null ? "Target IRR" : "Cash-on-Cash";
  const primaryReturnValue = headlineIrr !== null ? headlineIrr : headlineCashOnCash;

  return {
    headlineIrr,
    headlineCashOnCash,
    headlineMultiple,
    primaryReturnLabel,
    primaryReturnValue,
  };
}

export function isHoldReturnStrategy(value: unknown): boolean {
  const strategy = String(value ?? "").toLowerCase();
  return strategy === "hold" || strategy === "hold_with_sale_option";
}

function pickTrustedNumber(metrics: Metrics, provenance: ProvenanceMap, paths: string[]): number | null {
  const candidates = paths
    .map((path) => ({ path, value: asNumber(getPath(metrics, path)), provenance: provenance[path] }))
    .filter((candidate) => candidate.value !== null);

  if (candidates.length === 0) return null;
  const clean = candidates.filter((candidate) => !isBadSource(candidate.provenance));
  const reviewed = clean.find((candidate) => {
    const status = String(candidate.provenance?.status ?? "");
    return candidate.provenance?.locked || ["manual", "confirmed", "calculated"].includes(status);
  });
  return (reviewed ?? clean[0] ?? candidates[0]).value;
}

function isBadSource(provenance?: FieldProvenance): boolean {
  if (!provenance) return false;
  const status = String(provenance.status ?? "").toLowerCase();
  const conflictCount = Array.isArray(provenance.conflict) ? provenance.conflict.length : 0;
  return conflictCount > 1 || ["wrong", "missing", "unverifiable", "stale"].includes(status);
}

function getPath(data: unknown, path: string): unknown {
  let cur = data;
  for (const part of path.split(".")) {
    if (!cur || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[part];
  }
  return cur;
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value.replace(/[$,%x]/gi, "").replace(/,/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}
