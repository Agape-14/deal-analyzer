"use client";

import { motion } from "framer-motion";
import { Card } from "@/components/ui/card";
import { fmtMoney, fmtPct } from "@/lib/utils";
import type { WaterfallResponse } from "@/lib/types";

/**
 * Horizontal stacked bar per tier showing LP vs GP dollars. The widest
 * tier sets the scale; smaller tiers shrink proportionally.
 */
export function WaterfallChart({ data }: { data: WaterfallResponse }) {
  const maxTotal = Math.max(1, ...data.tiers.map((t) => t.total ?? 0));

  return (
    <Card elevated className="p-6">
      <div className="flex items-start justify-between gap-6 mb-5 flex-wrap">
        <div>
          <h3 className="text-base font-semibold tracking-tight">Distribution waterfall</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Tiered LP/GP splits from return of capital through promote tiers.
          </p>
        </div>
        <div className="flex items-center gap-5 text-right flex-wrap">
          <div>
            <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">LP Total</div>
            <div className="text-lg font-semibold tabular-nums mt-0.5 text-[hsl(var(--chart-1))]">
              {fmtMoney(data.totals.lp_total)}
            </div>
            <div className="text-[10px] text-muted-foreground">{fmtPct(data.totals.lp_pct, 1)}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">GP Total</div>
            <div className="text-lg font-semibold tabular-nums mt-0.5 text-[hsl(var(--chart-3))]">
              {fmtMoney(data.totals.gp_total)}
            </div>
            <div className="text-[10px] text-muted-foreground">{fmtPct(data.totals.gp_pct, 1)}</div>
          </div>
        </div>
      </div>

      <div className="space-y-4">
        {data.tiers.map((t, i) => {
          const total = t.total ?? 0;
          const relWidth = (total / maxTotal) * 100;
          const lpWidth = total > 0 ? ((t.lp_amount ?? 0) / total) * 100 : 0;
          const gpWidth = 100 - lpWidth;

          return (
            <div key={i}>
              <div className="flex items-center justify-between gap-3 mb-1.5">
                <div className="text-sm font-medium">{t.name}</div>
                <div className="text-sm tabular-nums font-semibold">{fmtMoney(total)}</div>
              </div>
              <div className="relative h-5 rounded-md bg-muted/40 overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${relWidth}%` }}
                  transition={{ duration: 0.7, delay: 0.05 * i, ease: [0.22, 1, 0.36, 1] }}
                  className="absolute inset-y-0 left-0 flex"
                >
                  <div className="bg-[hsl(var(--chart-1))]" style={{ width: `${lpWidth}%` }} />
                  <div className="bg-[hsl(var(--chart-3))]" style={{ width: `${gpWidth}%` }} />
                </motion.div>
              </div>
              <div className="mt-1 flex items-center gap-3 text-[10px] text-muted-foreground tabular-nums">
                <span>
                  LP {fmtPct(t.lp_pct, 0)} · {fmtMoney(t.lp_amount)}
                </span>
                <span>
                  GP {fmtPct(t.gp_pct, 0)} · {fmtMoney(t.gp_amount)}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {data.totals.your_total != null && (
        <div className="mt-6 pt-4 border-t border-border/60 flex items-center justify-between">
          <span className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
            Your projected net
          </span>
          <span className="text-base font-semibold tabular-nums">
            {fmtMoney(data.totals.your_total)}
          </span>
        </div>
      )}
    </Card>
  );
}
