import { fmtMoney, fmtMultiple, fmtPct } from "@/lib/utils";
import type { Format, Direction, MetricRow } from "./presets";

export function formatValue(value: unknown, format: Format): string {
  if (value == null || value === "") return "—";
  if (typeof value === "number" && Number.isNaN(value)) return "—";

  if (typeof value === "number") {
    switch (format) {
      case "money":
        return fmtMoney(value);
      case "percent":
        return fmtPct(value, 1);
      case "multiple":
        return fmtMultiple(value);
      case "years":
        return `${value} ${value === 1 ? "yr" : "yrs"}`;
      case "score":
        return `${value.toFixed(1)}/10`;
      case "integer":
        return Math.round(value).toLocaleString();
      case "number":
        return value.toFixed(2);
      case "text":
      default:
        return String(value);
    }
  }

  return String(value);
}

/** A row value paired with the deal id it came from. */
export interface CellValue {
  dealId: number;
  raw: unknown;
  num: number | null;
}

/**
 * Given a metric row and an ordered list of cell values (one per selected
 * deal), return two id-sets: winners and losers for highlighting. Only
 * numeric rows with a direction return anything; string/no-direction rows
 * return empty sets.
 */
export function findExtrema(
  row: MetricRow,
  cells: CellValue[],
): { winners: Set<number>; losers: Set<number> } {
  const winners = new Set<number>();
  const losers = new Set<number>();
  if (row.direction === "none") return { winners, losers };

  const numeric = cells.filter((c) => c.num != null) as Array<CellValue & { num: number }>;
  if (numeric.length < 2) return { winners, losers };

  const max = Math.max(...numeric.map((c) => c.num));
  const min = Math.min(...numeric.map((c) => c.num));
  if (max === min) return { winners, losers };

  const best = row.direction === "higher" ? max : min;
  const worst = row.direction === "higher" ? min : max;

  for (const c of numeric) {
    if (c.num === best) winners.add(c.dealId);
    if (c.num === worst) losers.add(c.dealId);
  }
  return { winners, losers };
}

export function toNumber(v: unknown): number | null {
  if (typeof v === "number" && !Number.isNaN(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v))) return Number(v);
  return null;
}

/** Per row, compute the min/max across the cell set for normalized view. */
export function normalize(row: MetricRow, cell: CellValue, all: CellValue[]): number | null {
  if (row.direction === "none") return null;
  if (cell.num == null) return null;
  const nums = all.map((c) => c.num).filter((n): n is number => n != null);
  if (nums.length === 0) return null;
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  if (max === min) return 1;
  const ratio = (cell.num - min) / (max - min);
  return row.direction === "higher" ? ratio : 1 - ratio;
}

/** Describe the direction as text (used in tooltips). */
export function directionLabel(d: Direction): string {
  if (d === "higher") return "Higher is better";
  if (d === "lower") return "Lower is better";
  return "";
}
