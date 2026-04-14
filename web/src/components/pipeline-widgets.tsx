"use client";

import * as React from "react";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip as RTooltip,
  Bar,
  BarChart,
  XAxis,
} from "recharts";
import Link from "next/link";
import { motion } from "framer-motion";
import {
  Activity,
  TrendingUp,
  Trophy,
  Clock,
  ArrowUpRight,
  Sparkles,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { AnimatedNumber } from "@/components/motion";
import { cn, fmtMoney, fmtPct } from "@/lib/utils";

/** The server response shape from /api/deals/pipeline/summary. */
export interface PipelineSummary {
  total_deals: number;
  by_status: Record<string, number>;
  velocity_6mo: Array<{ month: string; count: number }>;
  win_rate_pct_12mo: number | null;
  committed_12mo: number;
  passed_12mo: number;
  aging_deals: Array<{
    id: number;
    project_name: string;
    status: string;
    days_open: number | null;
  }>;
  aging_count: number;
  capital_deployed: number;
  pipeline_under_review: number;
  avg_score: number | null;
}

/**
 * Four-card widget strip for the Deals dashboard.
 *
 * Each card is a quick at-a-glance summary you'd glance at first thing
 * in the morning. The charts are intentionally tiny — sparkline-scale —
 * because the dashboard also has the full deal grid below.
 */
export function PipelineWidgets({ summary }: { summary: PipelineSummary }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-10">
      <VelocityCard summary={summary} />
      <WinRateCard summary={summary} />
      <CapitalCard summary={summary} />
      <AgingCard summary={summary} />
    </div>
  );
}

/* ------------------------- Velocity ------------------------- */

function VelocityCard({ summary }: { summary: PipelineSummary }) {
  const data = summary.velocity_6mo;
  const total6 = data.reduce((a, d) => a + d.count, 0);
  const last = data[data.length - 1]?.count ?? 0;
  const prev = data[data.length - 2]?.count ?? 0;
  const delta = last - prev;

  return (
    <Card elevated className="p-5 relative overflow-hidden">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
          <Activity className="h-3 w-3" />
          Velocity
        </div>
        <span className={cn("text-[10px] tabular-nums font-medium", deltaColor(delta))}>
          {delta > 0 ? "+" : ""}
          {delta} vs prev mo
        </span>
      </div>
      <div className="text-2xl font-semibold tabular-nums tracking-tight mt-1">
        <AnimatedNumber value={total6} /> <span className="text-muted-foreground text-sm font-normal">deals / 6mo</span>
      </div>
      <div className="mt-3 h-10">
        <ResponsiveContainer>
          <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="vel-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="hsl(var(--chart-1))" stopOpacity={0.6} />
                <stop offset="100%" stopColor="hsl(var(--chart-1))" stopOpacity={0} />
              </linearGradient>
            </defs>
            <Area
              type="monotone"
              dataKey="count"
              stroke="hsl(var(--chart-1))"
              strokeWidth={1.5}
              fill="url(#vel-fill)"
              isAnimationActive={false}
            />
            <RTooltip content={<MiniTooltip />} cursor={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

/* ------------------------- Win rate ------------------------- */

function WinRateCard({ summary }: { summary: PipelineSummary }) {
  const rate = summary.win_rate_pct_12mo;
  const color =
    rate == null
      ? "text-muted-foreground"
      : rate >= 60
        ? "text-success"
        : rate >= 30
          ? "text-primary"
          : "text-warning";

  return (
    <Card elevated className="p-5">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
          <Trophy className="h-3 w-3" />
          Win rate (12mo)
        </div>
      </div>
      <div className={cn("text-2xl font-semibold tabular-nums tracking-tight mt-1", color)}>
        {rate == null ? "—" : fmtPct(rate, 0)}
      </div>
      <div className="mt-1 text-xs text-muted-foreground tabular-nums">
        {summary.committed_12mo} committed · {summary.passed_12mo} passed
      </div>
      {/* Thin progress bar */}
      {rate != null && (
        <div className="mt-3 h-1 rounded-full bg-muted overflow-hidden">
          <motion.div
            className={cn(
              "h-full rounded-full",
              rate >= 60 ? "bg-success" : rate >= 30 ? "bg-primary" : "bg-warning",
            )}
            initial={{ width: 0 }}
            animate={{ width: `${Math.max(0, Math.min(100, rate))}%` }}
            transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
          />
        </div>
      )}
    </Card>
  );
}

/* ------------------------- Capital ------------------------- */

function CapitalCard({ summary }: { summary: PipelineSummary }) {
  return (
    <Card elevated className="p-5">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
          <TrendingUp className="h-3 w-3" />
          Capital deployed
        </div>
      </div>
      <div className="text-2xl font-semibold tabular-nums tracking-tight text-primary mt-1">
        <AnimatedNumber value={summary.capital_deployed} format={(n) => fmtMoney(n)} />
      </div>
      <div className="mt-1 text-xs text-muted-foreground">
        Under review: <span className="text-foreground tabular-nums">{fmtMoney(summary.pipeline_under_review)}</span>
      </div>
      {/* Tiny by-status bar */}
      <ByStatusBar by_status={summary.by_status} />
    </Card>
  );
}

function ByStatusBar({ by_status }: { by_status: Record<string, number> }) {
  const entries = (["reviewing", "interested", "committed", "closed", "passed"] as const).map((k) => ({
    key: k,
    count: by_status[k] ?? 0,
  }));
  const total = entries.reduce((a, e) => a + e.count, 0) || 1;
  return (
    <div className="mt-3 h-1.5 flex rounded-full overflow-hidden bg-muted">
      {entries.map((e) => (
        <motion.div
          key={e.key}
          initial={{ width: 0 }}
          animate={{ width: `${(e.count / total) * 100}%` }}
          transition={{ duration: 0.6 }}
          className={statusBarColor(e.key)}
          title={`${e.key}: ${e.count}`}
        />
      ))}
    </div>
  );
}

function statusBarColor(k: string): string {
  switch (k) {
    case "committed": return "bg-success";
    case "closed": return "bg-[hsl(var(--chart-3))]";
    case "interested": return "bg-primary";
    case "reviewing": return "bg-muted-foreground/30";
    case "passed": return "bg-destructive/60";
    default: return "bg-muted";
  }
}

/* ------------------------- Aging ------------------------- */

function AgingCard({ summary }: { summary: PipelineSummary }) {
  const deals = summary.aging_deals;
  const color = summary.aging_count === 0 ? "text-muted-foreground" : "text-warning";

  return (
    <Card elevated className="p-5 relative">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
          <Clock className="h-3 w-3" />
          Aging (&gt;30d)
        </div>
      </div>
      <div className={cn("text-2xl font-semibold tabular-nums tracking-tight mt-1", color)}>
        <AnimatedNumber value={summary.aging_count} />
      </div>
      <div className="mt-2 space-y-1">
        {deals.slice(0, 3).map((d) => (
          <Link
            key={d.id}
            href={`/deals/${d.id}`}
            className="flex items-center justify-between gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <span className="truncate">{d.project_name}</span>
            <span className="tabular-nums shrink-0">{d.days_open}d</span>
          </Link>
        ))}
        {deals.length === 0 && (
          <div className="text-xs text-muted-foreground">Nothing stuck. 🎯</div>
        )}
        {summary.aging_count > 3 && (
          <div className="text-[10px] text-muted-foreground pt-1">
            +{summary.aging_count - 3} more
          </div>
        )}
      </div>
    </Card>
  );
}

/* ------------------------- Misc ------------------------- */

function MiniTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: { month: string; count: number } }> }) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-md border border-border bg-popover text-popover-foreground px-2 py-1 text-[11px]">
      <div className="font-medium">{p.month}</div>
      <div className="tabular-nums">{p.count} deal{p.count === 1 ? "" : "s"}</div>
    </div>
  );
}

function deltaColor(d: number): string {
  if (d > 0) return "text-success";
  if (d < 0) return "text-destructive";
  return "text-muted-foreground";
}
