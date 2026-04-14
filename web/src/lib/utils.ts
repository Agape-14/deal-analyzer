import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind classes with proper override semantics. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Format a dollar amount with smart abbreviation (K / M / B). */
export function fmtMoney(val: number | null | undefined, opts: { compact?: boolean } = {}): string {
  if (val == null || Number.isNaN(val)) return "—";
  const n = Number(val);
  if (opts.compact !== false) {
    if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
    if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
    if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  }
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

/** Format a percentage (value already expressed as percent). */
export function fmtPct(val: number | null | undefined, digits = 1): string {
  if (val == null || Number.isNaN(val)) return "—";
  return `${Number(val).toFixed(digits)}%`;
}

/** Format an equity multiple. */
export function fmtMultiple(val: number | null | undefined): string {
  if (val == null || Number.isNaN(val)) return "—";
  return `${Number(val).toFixed(2)}x`;
}

/** Return a Tailwind class for delta coloring. */
export function deltaColor(val: number | null | undefined): string {
  if (val == null) return "text-muted-foreground";
  if (val > 0) return "text-success";
  if (val < 0) return "text-destructive";
  return "text-muted-foreground";
}

/** Format an ISO date as a readable short form ("Mar 14, 2025"). */
export function fmtDate(val: string | null | undefined, opts: { year?: boolean } = {}): string {
  if (!val) return "—";
  const d = new Date(val);
  if (Number.isNaN(d.getTime())) return val;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: opts.year === false ? undefined : "numeric",
  });
}

/** "Q1 2025" style period label from an ISO date. */
export function fmtQuarter(val: string | null | undefined): string {
  if (!val) return "—";
  const d = new Date(val);
  if (Number.isNaN(d.getTime())) return val;
  const q = Math.floor(d.getMonth() / 3) + 1;
  return `Q${q} ${d.getFullYear()}`;
}
