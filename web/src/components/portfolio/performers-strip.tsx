"use client";

import { Trophy, TrendingDown } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn, fmtMoney, fmtMultiple, fmtPct } from "@/lib/utils";
import type { Investment, InvestmentPerformance } from "@/lib/types";

/**
 * Top-3 / bottom-3 performers side-by-side. A scoped "hot and cold" view
 * that helps quickly flag winners and dogs when you don't want to scroll
 * the full grid.
 */
export function PerformersStrip({
  top,
  bottom,
  investments,
}: {
  top: InvestmentPerformance[];
  bottom: InvestmentPerformance[];
  investments: Investment[];
}) {
  const byId = new Map(investments.map((i) => [i.id, i]));

  if (top.length === 0 && bottom.length === 0) return null;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <PerformerCard
        title="Top performers"
        icon={Trophy}
        accent="success"
        rows={top}
        byId={byId}
      />
      <PerformerCard
        title="Bottom performers"
        icon={TrendingDown}
        accent="destructive"
        rows={bottom}
        byId={byId}
      />
    </div>
  );
}

function PerformerCard({
  title,
  icon: Icon,
  accent,
  rows,
  byId,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  accent: "success" | "destructive";
  rows: InvestmentPerformance[];
  byId: Map<number, Investment>;
}) {
  const color = accent === "success" ? "text-success" : "text-destructive";
  const bg = accent === "success" ? "bg-success/10 ring-success/30" : "bg-destructive/10 ring-destructive/30";

  return (
    <Card elevated className="p-6">
      <div className="flex items-center gap-2 mb-4">
        <span className={cn("h-7 w-7 rounded-lg grid place-items-center ring-1", bg)}>
          <Icon className={cn("h-3.5 w-3.5", color)} />
        </span>
        <h3 className="text-base font-semibold tracking-tight">{title}</h3>
      </div>

      {rows.length === 0 ? (
        <div className="text-xs text-muted-foreground py-4">Not enough data yet.</div>
      ) : (
        <ul className="divide-y divide-border/50">
          {rows.map((p) => {
            const inv = byId.get(p.investment_id);
            return (
              <li key={p.investment_id} className="py-3 flex items-center gap-4">
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium truncate">{inv?.project_name ?? `Investment #${p.investment_id}`}</div>
                  <div className="text-[11px] text-muted-foreground truncate mt-0.5">
                    {inv?.sponsor_name || "—"} · {fmtMoney(p.invested)} invested
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className={cn("text-sm font-semibold tabular-nums", color)}>
                    {fmtMultiple(p.multiple)}
                  </div>
                  <div className="text-[11px] text-muted-foreground tabular-nums">
                    {p.irr != null ? fmtPct(p.irr, 1) : "—"} IRR
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
