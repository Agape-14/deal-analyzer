"use client";

import { motion } from "framer-motion";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { Card } from "@/components/ui/card";
import { AnimatedNumber } from "@/components/motion";
import { cn, fmtMoney, fmtMultiple, fmtPct } from "@/lib/utils";
import type { PortfolioAnalytics } from "@/lib/types";

/**
 * The four-up KPI hero at the top of the Portfolio page. Every figure
 * animates from 0 on mount so the first paint feels like a dashboard,
 * not a spreadsheet. Delta chips below each figure give context at a glance.
 */
export function PortfolioHero({ analytics }: { analytics: PortfolioAnalytics }) {
  const s = analytics.summary;
  const net = s.total_returned - s.total_invested;
  const hasIrr = typeof s.overall_irr_pct === "number" && Number.isFinite(s.overall_irr_pct);

  // Show DPI (distributions only) as a contextual chip on Multiple
  const dpi = s.total_invested > 0 ? s.total_distributions / s.total_invested : 0;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <Kpi
        label="Total Invested"
        value={s.total_invested}
        format="money"
        sublabel={`${s.investment_count} position${s.investment_count === 1 ? "" : "s"}`}
      />
      <Kpi
        label="Total Returned"
        value={s.total_returned}
        format="money"
        sublabel={`DPI ${fmtMultiple(dpi)}`}
        accent="success"
      />
      <Kpi
        label="Net Position"
        value={net}
        format="money"
        accent={net >= 0 ? "success" : net < 0 ? "destructive" : undefined}
        sublabel={net >= 0 ? "In the green" : "Still in J-curve"}
        delta={{ value: net, format: "money" }}
      />
      <Kpi
        label="Overall Multiple"
        value={s.overall_multiple}
        format="multiple"
        sublabel={hasIrr ? `IRR ${fmtPct(s.overall_irr_pct, 1)}` : "IRR —"}
        accent={s.overall_multiple >= 1 ? "primary" : undefined}
      />
    </div>
  );
}

function Kpi({
  label,
  value,
  format,
  sublabel,
  accent,
  delta,
}: {
  label: string;
  value: number;
  format: "money" | "multiple" | "percent";
  sublabel?: string;
  accent?: "success" | "destructive" | "primary";
  delta?: { value: number; format: "money" | "percent" };
}) {
  const formatter =
    format === "money"
      ? (n: number) => fmtMoney(n)
      : format === "multiple"
        ? (n: number) => fmtMultiple(n)
        : (n: number) => fmtPct(n, 1);

  const valueColor = accent
    ? accent === "success"
      ? "text-success"
      : accent === "destructive"
        ? "text-destructive"
        : "text-primary"
    : "text-foreground";

  const DeltaIcon = delta
    ? delta.value > 0
      ? TrendingUp
      : delta.value < 0
        ? TrendingDown
        : Minus
    : null;
  const deltaColor =
    delta && delta.value > 0
      ? "text-success bg-success/10 ring-success/30"
      : delta && delta.value < 0
        ? "text-destructive bg-destructive/10 ring-destructive/30"
        : "text-muted-foreground bg-muted ring-border";

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
    >
      <Card elevated className="p-5 relative overflow-hidden">
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-border to-transparent" />
        <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
          {label}
        </div>
        <div className={cn("mt-3 text-2xl font-semibold tabular-nums tracking-tight", valueColor)}>
          <AnimatedNumber value={value} format={formatter} />
        </div>
        <div className="mt-2 flex items-center gap-2 text-xs">
          {DeltaIcon && (
            <span className={cn("inline-flex items-center gap-1 px-1.5 h-5 rounded-full ring-1 font-medium", deltaColor)}>
              <DeltaIcon className="h-3 w-3" />
              {delta!.format === "money" ? fmtMoney(delta!.value) : fmtPct(delta!.value, 1)}
            </span>
          )}
          {sublabel && <span className="text-muted-foreground">{sublabel}</span>}
        </div>
      </Card>
    </motion.div>
  );
}
