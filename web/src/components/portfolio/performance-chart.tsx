"use client";

import * as React from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  ComposedChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { motion, AnimatePresence } from "framer-motion";
import { Card } from "@/components/ui/card";
import { cn, fmtDate, fmtMoney, fmtMultiple } from "@/lib/utils";
import type { PortfolioAnalytics } from "@/lib/types";

type Metric = "cumulative" | "net_position" | "multiple";

const METRICS: Array<{ key: Metric; label: string }> = [
  { key: "cumulative", label: "Invested vs Returned" },
  { key: "net_position", label: "Net position" },
  { key: "multiple", label: "Multiple over time" },
];

/**
 * The hero chart. Switchable between:
 *   - Invested vs Returned (two stacked areas + net line)
 *   - Net position (area that dips below zero during the J-curve)
 *   - Multiple (line trending from 0 toward target)
 *
 * Hover gives a scrubbed readout of every metric at that date.
 */
export function PerformanceChart({ analytics }: { analytics: PortfolioAnalytics }) {
  const [metric, setMetric] = React.useState<Metric>("cumulative");
  const series = analytics.timeseries ?? [];

  return (
    <Card elevated className="p-6">
      <div className="flex items-start justify-between gap-4 flex-wrap mb-5">
        <div>
          <h3 className="text-base font-semibold tracking-tight">Portfolio performance</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Cumulative cashflows across all investments.
          </p>
        </div>
        <Segmented value={metric} onChange={setMetric} options={METRICS} />
      </div>

      {series.length === 0 ? (
        <div className="py-14 text-center text-sm text-muted-foreground">
          No cashflow history yet. Add distributions to see the curve build.
        </div>
      ) : (
        <div className="h-[320px] w-full">
          <ResponsiveContainer>
            {metric === "cumulative" ? (
              <ComposedChart data={series} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="pp-invested" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="hsl(var(--destructive))" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="hsl(var(--destructive))" stopOpacity={0.05} />
                  </linearGradient>
                  <linearGradient id="pp-returned" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="hsl(var(--chart-2))" stopOpacity={0.45} />
                    <stop offset="100%" stopColor="hsl(var(--chart-2))" stopOpacity={0.05} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={(v) => fmtDate(v, { year: false })} stroke="hsl(var(--muted-foreground))" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} minTickGap={40} />
                <YAxis tickFormatter={(v) => fmtMoney(v)} stroke="hsl(var(--muted-foreground))" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} width={56} />
                <Tooltip content={<PerfTooltip />} cursor={{ stroke: "hsl(var(--muted-foreground))", strokeDasharray: "3 3" }} />
                <Area type="monotone" dataKey="cumulative_invested" stroke="hsl(var(--destructive))" strokeWidth={2} fill="url(#pp-invested)" animationDuration={700} />
                <Area type="monotone" dataKey="cumulative_returned" stroke="hsl(var(--chart-2))" strokeWidth={2} fill="url(#pp-returned)" animationDuration={800} />
                <Line type="monotone" dataKey="net_position" stroke="hsl(var(--chart-3))" strokeWidth={2} dot={false} animationDuration={900} />
              </ComposedChart>
            ) : metric === "net_position" ? (
              <AreaChart data={series} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="pp-net" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="hsl(var(--chart-1))" stopOpacity={0.45} />
                    <stop offset="100%" stopColor="hsl(var(--chart-1))" stopOpacity={0.05} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={(v) => fmtDate(v, { year: false })} stroke="hsl(var(--muted-foreground))" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} minTickGap={40} />
                <YAxis tickFormatter={(v) => fmtMoney(v)} stroke="hsl(var(--muted-foreground))" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} width={56} />
                <Tooltip content={<PerfTooltip />} cursor={{ stroke: "hsl(var(--muted-foreground))", strokeDasharray: "3 3" }} />
                <ReferenceLine y={0} stroke="hsl(var(--border))" />
                <Area type="monotone" dataKey="net_position" stroke="hsl(var(--chart-1))" strokeWidth={2} fill="url(#pp-net)" animationDuration={700} />
              </AreaChart>
            ) : (
              <AreaChart data={series} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="pp-mult" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity={0.45} />
                    <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity={0.05} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={(v) => fmtDate(v, { year: false })} stroke="hsl(var(--muted-foreground))" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} minTickGap={40} />
                <YAxis tickFormatter={(v) => `${v.toFixed(2)}x`} stroke="hsl(var(--muted-foreground))" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} width={56} domain={[0, "auto"]} />
                <Tooltip content={<PerfTooltip />} cursor={{ stroke: "hsl(var(--muted-foreground))", strokeDasharray: "3 3" }} />
                <ReferenceLine y={1} stroke="hsl(var(--border))" strokeDasharray="4 4" />
                <Area type="monotone" dataKey="multiple" stroke="hsl(var(--primary))" strokeWidth={2} fill="url(#pp-mult)" animationDuration={700} />
              </AreaChart>
            )}
          </ResponsiveContainer>
        </div>
      )}

      <div className="mt-4 flex items-center gap-5 text-xs text-muted-foreground flex-wrap">
        {metric === "cumulative" && (
          <>
            <LegendSwatch color="hsl(var(--destructive))">Cumulative invested</LegendSwatch>
            <LegendSwatch color="hsl(var(--chart-2))">Cumulative returned</LegendSwatch>
            <LegendLine color="hsl(var(--chart-3))">Net position</LegendLine>
          </>
        )}
        {metric === "net_position" && <LegendSwatch color="hsl(var(--chart-1))">Net position ({"$"}returned − ${"$"}invested)</LegendSwatch>}
        {metric === "multiple" && (
          <>
            <LegendSwatch color="hsl(var(--primary))">Cumulative multiple</LegendSwatch>
            <span className="opacity-70">dashed line = breakeven (1.0x)</span>
          </>
        )}
      </div>
    </Card>
  );
}

function Segmented<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: Array<{ key: T; label: string }>;
}) {
  return (
    <div className="inline-flex items-center gap-0.5 p-1 rounded-lg bg-secondary/40 border border-border/70 text-xs">
      {options.map((o) => {
        const active = o.key === value;
        return (
          <button
            key={o.key}
            onClick={() => onChange(o.key)}
            className={cn(
              "relative px-2.5 h-7 rounded-md font-medium transition-colors",
              active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {active && (
              <AnimatePresence>
                <motion.span
                  layoutId="perf-seg"
                  className="absolute inset-0 rounded-md bg-card ring-1 ring-border/80 shadow-sm"
                  transition={{ type: "spring", stiffness: 420, damping: 32 }}
                />
              </AnimatePresence>
            )}
            <span className="relative">{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}

function PerfTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{
    payload: {
      date: string;
      cumulative_invested: number;
      cumulative_returned: number;
      net_position: number;
      multiple: number;
    };
  }>;
}) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-lg border border-border bg-popover text-popover-foreground shadow-lg px-3 py-2 text-xs">
      <div className="font-semibold mb-1.5">{fmtDate(p.date)}</div>
      <Row label="Invested" value={fmtMoney(p.cumulative_invested)} color="text-destructive" />
      <Row label="Returned" value={fmtMoney(p.cumulative_returned)} color="text-[hsl(var(--chart-2))]" />
      <Row label="Net" value={fmtMoney(p.net_position)} />
      <Row label="Multiple" value={fmtMultiple(p.multiple)} />
    </div>
  );
}

function Row({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex justify-between gap-4 leading-5">
      <span className={cn("text-muted-foreground", color)}>{label}</span>
      <span className="font-medium tabular-nums">{value}</span>
    </div>
  );
}

function LegendSwatch({ color, children }: { color: string; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-2 w-4 rounded-sm" style={{ background: color }} />
      {children}
    </span>
  );
}

function LegendLine({ color, children }: { color: string; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-0.5 w-4" style={{ background: color }} />
      {children}
    </span>
  );
}
