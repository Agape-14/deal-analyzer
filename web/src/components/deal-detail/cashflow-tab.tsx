"use client";

import * as React from "react";
import { Loader2, AlertCircle } from "lucide-react";
import { Card } from "@/components/ui/card";
import { CashflowChart } from "@/components/deal-detail/cashflow-chart";
import { WaterfallChart } from "@/components/deal-detail/waterfall-chart";
import { api } from "@/lib/api";
import { fmtMoney } from "@/lib/utils";
import type { CashflowResponse, WaterfallResponse } from "@/lib/types";

/**
 * Lazily fetches cashflow + waterfall on mount. The backend computes both
 * on the fly — no DB writes — so it's safe to call whenever the tab opens.
 */
export function CashflowTab({ dealId, projectedIrr }: { dealId: number; projectedIrr?: number | null }) {
  const [cf, setCf] = React.useState<CashflowResponse | null>(null);
  const [wf, setWf] = React.useState<WaterfallResponse | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    setLoading(true);
    Promise.all([
      api.get<CashflowResponse>(`/api/deals/${dealId}/cashflow`),
      api.get<WaterfallResponse>(`/api/deals/${dealId}/waterfall`),
    ])
      .then(([c, w]) => {
        setCf(c);
        setWf(w);
      })
      .catch((e) => {
        setError((e as { detail?: string })?.detail ?? "Couldn't compute cashflow");
      })
      .finally(() => setLoading(false));
  }, [dealId]);

  if (loading) {
    return (
      <Card elevated className="p-12 flex items-center justify-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Computing cashflow projections…
      </Card>
    );
  }

  if (error) {
    return (
      <Card elevated className="p-8 text-center">
        <AlertCircle className="h-5 w-5 text-destructive mx-auto mb-2" />
        <div className="text-sm font-medium text-destructive">Couldn&apos;t compute cashflow</div>
        <div className="text-xs text-muted-foreground mt-1 max-w-md mx-auto">{error}</div>
        <div className="text-xs text-muted-foreground mt-3">
          This usually means the deal is missing IRR, hold period, or capitalization structure — extract metrics from an OM first.
        </div>
      </Card>
    );
  }

  if (!cf || !wf) return null;

  return (
    <div className="space-y-6">
      <CashflowChart data={cf} projectedIrr={projectedIrr ?? null} />
      <WaterfallChart data={wf} />
      <YearlyTable cf={cf} />
    </div>
  );
}

function YearlyTable({ cf }: { cf: CashflowResponse }) {
  if (!cf.project_level || cf.project_level.length === 0) return null;
  return (
    <Card elevated className="p-6 overflow-hidden">
      <h3 className="text-base font-semibold tracking-tight mb-4">Year-by-year (project level)</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
              <th className="text-left py-2 pr-4 font-medium">Year</th>
              <th className="text-right py-2 px-4 font-medium">Revenue</th>
              <th className="text-right py-2 px-4 font-medium">Expenses</th>
              <th className="text-right py-2 px-4 font-medium">NOI</th>
              <th className="text-right py-2 px-4 font-medium">Debt Service</th>
              <th className="text-right py-2 pl-4 font-medium">Cash Flow</th>
            </tr>
          </thead>
          <tbody>
            {cf.project_level.map((row) => (
              <tr key={row.year} className="border-t border-border/50">
                <td className="py-2 pr-4 font-medium">Y{row.year}</td>
                <td className="py-2 px-4 text-right tabular-nums">{fmtMoney(row.gross_revenue)}</td>
                <td className="py-2 px-4 text-right tabular-nums">{fmtMoney(row.expenses)}</td>
                <td className="py-2 px-4 text-right tabular-nums">{fmtMoney(row.noi)}</td>
                <td className="py-2 px-4 text-right tabular-nums text-muted-foreground">
                  {fmtMoney(row.debt_service)}
                </td>
                <td className="py-2 pl-4 text-right tabular-nums font-semibold">{fmtMoney(row.cash_flow)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
