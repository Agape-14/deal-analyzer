"use client";

import * as React from "react";
import {
  Area,
  CartesianGrid,
  Line,
  ComposedChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card } from "@/components/ui/card";
import { fmtMoney, fmtMultiple, fmtPct } from "@/lib/utils";
import type { CashflowResponse } from "@/lib/types";

/**
 * Cashflow area chart with a cumulative line overlay.
 *
 * Derives the year-by-year series from either `lp_level` (when populated) or
 * `project_level.cash_flow` (common fallback — the backend often leaves
 * lp_level empty and encodes returns at the project level). Exit proceeds
 * are added to the terminal year so the chart reflects the full round-trip.
 */
export function CashflowChart({
  data,
  projectedIrr,
}: {
  data: CashflowResponse;
  projectedIrr?: number | null;
}) {
  const series = React.useMemo(() => {
    // Prefer LP-level series if populated, fall back to project_level
    type Row = { year: number; cf: number; cumulative: number; noi?: number };
    const rows: Row[] = [];

    if (data.lp_level && data.lp_level.length) {
      for (const r of data.lp_level) {
        rows.push({ year: r.year, cf: r.amount, cumulative: r.cumulative });
      }
    } else if (data.project_level?.length) {
      // Year 0 = invested equity (negative), then annual cash_flow, then exit
      const investedEquity = data.summary?.exit_equity
        ? data.summary.exit_value
          ? Math.max(0, data.summary.exit_value - data.summary.exit_equity) === 0
            ? 0
            : 0 // placeholder — we don't have explicit invested equity
          : 0
        : 0;
      // The project_level doesn't include equity-in, so display just the
      // operating cashflow; cumulative starts at 0 and grows.
      let cum = 0;
      for (const y of data.project_level) {
        cum += y.cash_flow;
        rows.push({ year: y.year, cf: y.cash_flow, cumulative: cum, noi: y.noi });
      }
      // Add exit proceeds to terminal year for visual impact
      if (data.summary?.exit_equity && rows.length) {
        const last = rows[rows.length - 1];
        last.cf += data.summary.exit_equity;
        last.cumulative += data.summary.exit_equity;
      }
      void investedEquity; // reserved for when backend exposes equity-in
    }
    return rows;
  }, [data]);

  const summary = data.summary;

  return (
    <Card elevated className="p-6">
      <div className="flex items-start justify-between gap-6 mb-5 flex-wrap">
        <div>
          <h3 className="text-base font-semibold tracking-tight">Cashflow projection</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            LP-level cash flow with cumulative return overlay.
          </p>
        </div>
        <div className="flex items-center gap-5 text-right flex-wrap">
          {projectedIrr != null && (
            <SummaryStat label="Target IRR" value={fmtPct(projectedIrr, 1)} accent="primary" />
          )}
          <SummaryStat label="Multiple" value={fmtMultiple(summary.equity_multiple)} />
          <SummaryStat label="Exit Equity" value={fmtMoney(summary.exit_equity)} accent="success" />
          <SummaryStat label="Total Return" value={fmtMoney(summary.total_return_to_equity)} />
        </div>
      </div>

      {series.length > 0 ? (
        <div className="h-[280px] w-full">
          <ResponsiveContainer>
            <ComposedChart data={series} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="cf-pos" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="hsl(var(--chart-1))" stopOpacity={0.55} />
                  <stop offset="100%" stopColor="hsl(var(--chart-1))" stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeDasharray="3 3" />
              <XAxis
                dataKey="year"
                tickFormatter={(v) => (v === 0 ? "Y0" : `Y${v}`)}
                stroke="hsl(var(--muted-foreground))"
                tick={{ fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tickFormatter={(v) => fmtMoney(v)}
                stroke="hsl(var(--muted-foreground))"
                tick={{ fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={56}
              />
              <Tooltip
                content={<CFTooltip />}
                cursor={{ stroke: "hsl(var(--muted-foreground))", strokeDasharray: "3 3" }}
              />
              <ReferenceLine y={0} stroke="hsl(var(--border))" />
              <Area
                type="monotone"
                dataKey="cf"
                stroke="hsl(var(--chart-1))"
                strokeWidth={2}
                fill="url(#cf-pos)"
                animationDuration={800}
                animationEasing="ease-out"
              />
              <Line
                type="monotone"
                dataKey="cumulative"
                stroke="hsl(var(--chart-3))"
                strokeWidth={2}
                dot={false}
                animationDuration={900}
                animationEasing="ease-out"
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="py-16 text-center text-sm text-muted-foreground">
          No cashflow series available yet.
        </div>
      )}

      <div className="mt-4 flex items-center gap-5 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-4 rounded-sm bg-[hsl(var(--chart-1))]" /> Net cashflow
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-0.5 w-4 bg-[hsl(var(--chart-3))]" /> Cumulative position
        </span>
      </div>
    </Card>
  );
}

function CFTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: { year: number; cf: number; cumulative: number; noi?: number } }>;
}) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-lg border border-border bg-popover text-popover-foreground shadow-lg px-3 py-2 text-xs">
      <div className="font-semibold mb-1.5">Year {p.year}</div>
      <Row label="Net CF" value={fmtMoney(p.cf)} />
      <Row label="Cumulative" value={fmtMoney(p.cumulative)} />
      {p.noi != null && <Row label="NOI" value={fmtMoney(p.noi)} />}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium tabular-nums">{value}</span>
    </div>
  );
}

function SummaryStat({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: "primary" | "success" | "destructive";
}) {
  const color =
    accent === "primary"
      ? "text-primary"
      : accent === "success"
        ? "text-success"
        : accent === "destructive"
          ? "text-destructive"
          : "text-foreground";
  return (
    <div>
      <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">{label}</div>
      <div className={`text-lg font-semibold tabular-nums mt-0.5 ${color}`}>{value}</div>
    </div>
  );
}
