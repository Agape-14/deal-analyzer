"use client";

import { Card } from "@/components/ui/card";
import { AnimatedNumber } from "@/components/motion";
import { cn, fmtMoney, fmtPct, fmtMultiple } from "@/lib/utils";

// We accept a format key (serializable) rather than a function so that
// Server Components can pass the prop across the RSC boundary.
type FormatKey = "number" | "money" | "percent" | "multiple" | "score";

const FORMATTERS: Record<FormatKey, (n: number) => string> = {
  number: (n) => Math.round(n).toLocaleString(),
  money: (n) => fmtMoney(n),
  percent: (n) => fmtPct(n),
  multiple: (n) => fmtMultiple(n),
  score: (n) => (n > 0 ? n.toFixed(1) : "—"),
};

/**
 * Premium stat card. Large display number with an animated ticker, optional
 * delta, and a gradient top-rim for a high-end feel.
 */
export function StatCard({
  label,
  value,
  format = "number",
  delta,
  deltaLabel,
  accent,
}: {
  label: string;
  value: number;
  format?: FormatKey;
  delta?: number | null;
  deltaLabel?: string;
  accent?: "success" | "destructive" | "primary";
}) {
  const formatter = FORMATTERS[format];

  const deltaColor =
    delta == null
      ? "text-muted-foreground"
      : delta > 0
        ? "text-success"
        : delta < 0
          ? "text-destructive"
          : "text-muted-foreground";

  const valueColor = accent
    ? accent === "success"
      ? "text-success"
      : accent === "destructive"
        ? "text-destructive"
        : "text-primary"
    : "text-foreground";

  return (
    <Card
      elevated
      className="p-5 relative overflow-hidden group transition-transform duration-200 hover:-translate-y-0.5"
    >
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-border to-transparent" />
      <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground mb-3">{label}</div>
      <div className={cn("text-2xl font-semibold tabular-nums tracking-tight", valueColor)}>
        <AnimatedNumber value={value} format={formatter} />
      </div>
      {delta != null && (
        <div className={cn("mt-1.5 text-xs flex items-center gap-1.5", deltaColor)}>
          <span className="tabular-nums font-medium">
            {delta > 0 ? "+" : ""}
            {delta.toFixed(2)}
            {typeof deltaLabel === "string" ? "" : "%"}
          </span>
          {deltaLabel && <span className="text-muted-foreground">{deltaLabel}</span>}
        </div>
      )}
    </Card>
  );
}
