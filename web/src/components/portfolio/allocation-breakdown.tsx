"use client";

import * as React from "react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { motion } from "framer-motion";
import { Card } from "@/components/ui/card";
import { fmtMoney, fmtMultiple, fmtPct } from "@/lib/utils";
import type { PortfolioAnalytics } from "@/lib/types";

const STATUS_COLORS: Record<string, string> = {
  active: "hsl(var(--chart-1))",
  exited: "hsl(var(--chart-2))",
  defaulted: "hsl(var(--destructive))",
  pending: "hsl(var(--muted-foreground))",
};

const STATUS_LABEL: Record<string, string> = {
  active: "Active",
  exited: "Exited",
  defaulted: "Defaulted",
  pending: "Pending",
};

export function AllocationBreakdown({ analytics }: { analytics: PortfolioAnalytics }) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_1.4fr] gap-6">
      <ByStatus analytics={analytics} />
      <BySponsor analytics={analytics} />
    </div>
  );
}

function ByStatus({ analytics }: { analytics: PortfolioAnalytics }) {
  const rows = analytics.by_status ?? [];
  const data = rows.map((r) => ({
    name: STATUS_LABEL[r.name] ?? r.name,
    key: r.name,
    value: r.invested,
    count: r.count,
    share: r.share_pct,
    multiple: r.multiple,
  }));

  if (data.length === 0) {
    return (
      <Card elevated className="p-6 min-h-[260px] grid place-items-center">
        <div className="text-sm text-muted-foreground">No positions yet.</div>
      </Card>
    );
  }

  return (
    <Card elevated className="p-6">
      <h3 className="text-base font-semibold tracking-tight mb-1">By status</h3>
      <p className="text-xs text-muted-foreground mb-5">Capital allocation across lifecycle stage.</p>

      <div className="flex items-center gap-6">
        <div className="h-[180px] w-[180px] shrink-0">
          <ResponsiveContainer>
            <PieChart>
              <Pie
                data={data}
                innerRadius={60}
                outerRadius={85}
                paddingAngle={2}
                dataKey="value"
                nameKey="name"
                strokeWidth={0}
                animationDuration={700}
              >
                {data.map((d) => (
                  <Cell key={d.key} fill={STATUS_COLORS[d.key] ?? "hsl(var(--muted-foreground))"} />
                ))}
              </Pie>
              <Tooltip content={<StatusTooltip />} />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div className="flex-1 min-w-0 space-y-2.5">
          {data.map((d) => (
            <div key={d.key} className="flex items-center gap-3 text-sm">
              <span
                className="h-2 w-2 rounded-full shrink-0"
                style={{ background: STATUS_COLORS[d.key] ?? "hsl(var(--muted-foreground))" }}
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium truncate">{d.name}</span>
                  <span className="tabular-nums text-muted-foreground text-xs">{fmtPct(d.share, 0)}</span>
                </div>
                <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                  <span>
                    {d.count} {d.count === 1 ? "position" : "positions"} · {fmtMoney(d.value)}
                  </span>
                  <span className="tabular-nums">{fmtMultiple(d.multiple)}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}

function StatusTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: { name: string; count: number; value: number; share: number; multiple: number } }>;
}) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-lg border border-border bg-popover text-popover-foreground shadow-lg px-3 py-2 text-xs">
      <div className="font-semibold mb-1">{p.name}</div>
      <div className="text-muted-foreground">{p.count} positions · {fmtPct(p.share, 1)}</div>
      <div className="mt-1 tabular-nums">{fmtMoney(p.value)} · {fmtMultiple(p.multiple)}</div>
    </div>
  );
}

function BySponsor({ analytics }: { analytics: PortfolioAnalytics }) {
  const rows = [...(analytics.by_sponsor ?? [])].sort((a, b) => b.invested - a.invested);
  const max = Math.max(1, ...rows.map((r) => r.invested));

  return (
    <Card elevated className="p-6">
      <h3 className="text-base font-semibold tracking-tight mb-1">By sponsor</h3>
      <p className="text-xs text-muted-foreground mb-5">Concentration and performance by GP.</p>

      {rows.length === 0 ? (
        <div className="py-10 text-center text-sm text-muted-foreground">No sponsors yet.</div>
      ) : (
        <div className="space-y-3.5">
          {rows.map((r, i) => {
            const pct = (r.invested / max) * 100;
            return (
              <div key={r.name}>
                <div className="flex items-center justify-between gap-3 mb-1.5">
                  <div className="min-w-0 flex items-center gap-2">
                    <span className="text-sm font-medium truncate">{r.name}</span>
                    <span className="text-[10px] uppercase tracking-wider text-muted-foreground border border-border/60 rounded px-1.5 py-0.5">
                      {r.count}
                    </span>
                  </div>
                  <div className="flex items-center gap-4 text-sm tabular-nums">
                    <span>{fmtMoney(r.invested)}</span>
                    <span className="text-muted-foreground">{fmtMultiple(r.multiple)}</span>
                  </div>
                </div>
                <div className="relative h-1.5 rounded-full bg-muted overflow-hidden">
                  <motion.div
                    className="absolute inset-y-0 left-0 bg-primary rounded-full"
                    initial={{ width: 0 }}
                    animate={{ width: `${pct}%` }}
                    transition={{ duration: 0.7, delay: 0.05 * i, ease: [0.22, 1, 0.36, 1] }}
                  />
                </div>
                <div className="mt-0.5 text-[10px] text-muted-foreground tabular-nums">
                  {fmtPct(r.share_pct, 1)} of capital · {fmtMoney(r.returned)} returned
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
