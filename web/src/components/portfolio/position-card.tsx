"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { Area, AreaChart, ResponsiveContainer } from "recharts";
import { MoreHorizontal, Plus, CheckSquare, Trash2, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { useRouter } from "next/navigation";
import { Card } from "@/components/ui/card";
import { cn, fmtMoney, fmtMultiple, fmtPct, fmtDate } from "@/lib/utils";
import { api } from "@/lib/api";
import type { Investment, InvestmentPerformance } from "@/lib/types";

const STATUS_STYLES: Record<string, string> = {
  active: "bg-primary/15 text-primary ring-1 ring-primary/30",
  exited: "bg-success/15 text-success ring-1 ring-success/30",
  defaulted: "bg-destructive/15 text-destructive ring-1 ring-destructive/30",
  pending: "bg-muted/60 text-muted-foreground",
};

/**
 * One investment, at-a-glance. Shows:
 *   - Project + sponsor + status chip
 *   - The big number: current multiple (color-graded)
 *   - IRR with "vs projected" delta chip when projected exists
 *   - Sparkline of cumulative_multiple over time
 *   - Invested / Returned / DPI micro-stats
 *   - Per-position actions menu: add distribution, mark exit, delete
 */
export function PositionCard({
  investment,
  performance,
  onAddDistribution,
  onMarkExit,
}: {
  investment: Investment;
  performance?: InvestmentPerformance;
  onAddDistribution: (inv: Investment) => void;
  onMarkExit: (inv: Investment) => void;
}) {
  const router = useRouter();
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);

  const mult = performance?.multiple ?? investment.actual_multiple ?? 0;
  const multColor =
    mult >= 1.5
      ? "text-success"
      : mult >= 1
        ? "text-primary"
        : mult >= 0.5
          ? "text-warning"
          : "text-destructive";

  const irr = performance?.irr ?? null;
  const projectedIrr = investment.projected_irr ?? null;
  const irrDelta = performance?.irr_vs_projected ?? null;

  const series =
    performance?.cumulative_timeseries?.map((r) => ({
      x: r.date,
      y: r.cumulative_multiple,
    })) ?? [];

  async function handleDelete() {
    if (!confirm(`Delete investment in "${investment.project_name}"?`)) return;
    setDeleting(true);
    try {
      await api.delete(`/api/investments/${investment.id}`);
      toast.success("Investment deleted");
      router.refresh();
    } catch (e) {
      toast.error("Couldn't delete", { description: (e as { detail?: string })?.detail });
    } finally {
      setDeleting(false);
      setMenuOpen(false);
    }
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
    >
      <Card elevated className="p-5 relative group">
        {/* Header */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h3 className="text-base font-semibold tracking-tight truncate">
                {investment.project_name}
              </h3>
              <span
                className={cn(
                  "px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wider font-medium",
                  STATUS_STYLES[investment.status] ?? STATUS_STYLES.pending,
                )}
              >
                {investment.status}
              </span>
            </div>
            <div className="text-xs text-muted-foreground mt-0.5 truncate">
              {investment.sponsor_name || "—"}
              {investment.investment_date && (
                <>
                  <span className="mx-1.5 opacity-40">·</span>
                  {fmtDate(investment.investment_date)}
                </>
              )}
            </div>
          </div>

          {/* Actions */}
          <div className="relative">
            <button
              onClick={() => setMenuOpen((o) => !o)}
              onBlur={() => setTimeout(() => setMenuOpen(false), 150)}
              className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 opacity-0 group-hover:opacity-100 transition-opacity focus-visible:opacity-100"
              aria-label="Position actions"
            >
              <MoreHorizontal className="h-4 w-4" />
            </button>
            {menuOpen && (
              <motion.div
                initial={{ opacity: 0, y: -4, scale: 0.96 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                transition={{ duration: 0.12 }}
                className="absolute right-0 top-full mt-1 w-48 rounded-lg border border-border/80 bg-card shadow-[0_20px_60px_-20px_rgba(0,0,0,0.9)] p-1 z-20"
              >
                <MenuItem
                  icon={Plus}
                  onClick={() => {
                    setMenuOpen(false);
                    onAddDistribution(investment);
                  }}
                >
                  Add distribution
                </MenuItem>
                {investment.status !== "exited" && (
                  <MenuItem
                    icon={CheckSquare}
                    onClick={() => {
                      setMenuOpen(false);
                      onMarkExit(investment);
                    }}
                  >
                    Mark exited…
                  </MenuItem>
                )}
                <MenuItem icon={deleting ? Loader2 : Trash2} onClick={handleDelete} destructive spin={deleting}>
                  Delete
                </MenuItem>
              </motion.div>
            )}
          </div>
        </div>

        {/* Big number */}
        <div className="mt-5 flex items-end justify-between gap-4">
          <div>
            <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
              Current Multiple
            </div>
            <div className={cn("text-3xl font-semibold tabular-nums leading-none mt-1.5", multColor)}>
              {fmtMultiple(mult)}
            </div>
            {irr != null && (
              <div className="mt-2 flex items-center gap-1.5 text-xs">
                <span className="tabular-nums font-medium">
                  IRR {fmtPct(irr, 1)}
                </span>
                {projectedIrr != null && irrDelta != null && (
                  <span
                    className={cn(
                      "inline-flex items-center gap-0.5 px-1.5 h-5 rounded-full ring-1 text-[10px] font-medium tabular-nums",
                      irrDelta >= 0
                        ? "text-success bg-success/10 ring-success/30"
                        : "text-destructive bg-destructive/10 ring-destructive/30",
                    )}
                    title={`vs projected ${fmtPct(projectedIrr, 1)}`}
                  >
                    {irrDelta >= 0 ? "+" : ""}
                    {irrDelta.toFixed(1)}
                  </span>
                )}
              </div>
            )}
          </div>

          {/* Sparkline */}
          {series.length > 1 && (
            <div className="h-14 w-32 shrink-0">
              <ResponsiveContainer>
                <AreaChart data={series} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id={`spark-${investment.id}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="hsl(var(--chart-1))" stopOpacity={0.55} />
                      <stop offset="100%" stopColor="hsl(var(--chart-1))" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <Area
                    type="monotone"
                    dataKey="y"
                    stroke="hsl(var(--chart-1))"
                    strokeWidth={1.5}
                    fill={`url(#spark-${investment.id})`}
                    isAnimationActive={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {/* Footer stats */}
        <div className="mt-5 pt-4 border-t border-border/50 grid grid-cols-3 gap-3 text-xs">
          <Stat label="Invested" value={fmtMoney(investment.amount_invested)} />
          <Stat label="Returned" value={fmtMoney(investment.total_returned)} />
          <Stat
            label="DPI"
            value={
              investment.amount_invested > 0
                ? fmtMultiple(investment.total_distributions / investment.amount_invested)
                : "—"
            }
          />
        </div>
      </Card>
    </motion.div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="font-semibold tabular-nums mt-0.5">{value}</div>
    </div>
  );
}

function MenuItem({
  icon: Icon,
  children,
  onClick,
  destructive,
  spin,
}: {
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
  onClick: () => void;
  destructive?: boolean;
  spin?: boolean;
}) {
  return (
    <button
      onMouseDown={(e) => {
        e.preventDefault();
        onClick();
      }}
      className={cn(
        "w-full flex items-center gap-2 px-2.5 h-8 rounded-md text-xs font-medium transition-colors",
        destructive
          ? "text-destructive hover:bg-destructive/10"
          : "text-muted-foreground hover:text-foreground hover:bg-muted/60",
      )}
    >
      <Icon className={cn("h-3.5 w-3.5", spin && "animate-spin")} />
      {children}
    </button>
  );
}
