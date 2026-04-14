"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { Crown, ArrowDown, ArrowUp, Info } from "lucide-react";
import { cn, fmtMoney, fmtMultiple, fmtPct } from "@/lib/utils";
import type { DealDetail } from "@/lib/types";
import { getValueAt, type MetricRow } from "./presets";
import { findExtrema, formatValue, normalize, toNumber, type CellValue } from "./value-format";

export type CompareMode = "values" | "winners" | "deltas" | "normalized";

/**
 * Groups rows by their category and renders a sticky-group-header table.
 * Keeps a rolling win counter and calls `onWins` whenever it changes so the
 * header row can show "Best overall" crowns.
 */
export function MetricsTable({
  deals,
  rows,
  mode,
  baselineId,
  onWins,
  cols,
}: {
  deals: DealDetail[];
  rows: MetricRow[];
  mode: CompareMode;
  baselineId: number | null;
  onWins: (wins: Record<number, number>) => void;
  cols: number;
}) {
  const grouped = React.useMemo(() => {
    const m = new Map<string, MetricRow[]>();
    for (const r of rows) {
      if (!m.has(r.group)) m.set(r.group, []);
      m.get(r.group)!.push(r);
    }
    return [...m.entries()];
  }, [rows]);

  // Precompute winners per row + tally total wins per deal
  const { winsByDeal, winsPerRow } = React.useMemo(() => {
    const wins: Record<number, number> = {};
    const perRow = new Map<string, { winners: Set<number>; losers: Set<number> }>();
    for (const r of rows) {
      const cells: CellValue[] = deals.map((d) => {
        const raw = getValueAt(d, r.path);
        return { dealId: d.id, raw, num: toNumber(raw) };
      });
      const ex = findExtrema(r, cells);
      perRow.set(r.key, ex);
      ex.winners.forEach((id) => {
        wins[id] = (wins[id] ?? 0) + 1;
      });
    }
    return { winsByDeal: wins, winsPerRow: perRow };
  }, [rows, deals]);

  React.useEffect(() => {
    onWins(winsByDeal);
  }, [winsByDeal, onWins]);

  const baseline = deals.find((d) => d.id === baselineId) ?? null;

  return (
    <div className="pt-4">
      {grouped.map(([group, groupRows], gi) => (
        <div key={group} className="mb-5">
          <div className="sticky top-[calc(64px+124px)] z-10 bg-background/85 backdrop-blur-md -mx-6 md:-mx-10 px-6 md:px-10 py-2 border-b border-border/60">
            <div className="text-[10px] uppercase tracking-[0.14em] font-semibold text-muted-foreground">
              {group}
            </div>
          </div>

          <div className="rounded-xl border border-border/80 bg-card overflow-x-auto">
            {groupRows.map((row, ri) => (
              <RowLine
                key={row.key}
                row={row}
                deals={deals}
                mode={mode}
                winners={winsPerRow.get(row.key)?.winners ?? new Set()}
                losers={winsPerRow.get(row.key)?.losers ?? new Set()}
                baseline={baseline}
                cols={cols}
                delayStep={gi * 0.01 + ri * 0.01}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function RowLine({
  row,
  deals,
  mode,
  winners,
  losers,
  baseline,
  cols,
  delayStep,
}: {
  row: MetricRow;
  deals: DealDetail[];
  mode: CompareMode;
  winners: Set<number>;
  losers: Set<number>;
  baseline: DealDetail | null;
  cols: number;
  delayStep: number;
}) {
  const cells: CellValue[] = deals.map((d) => {
    const raw = getValueAt(d, row.path);
    return { dealId: d.id, raw, num: toNumber(raw) };
  });

  return (
    <motion.div
      initial={{ opacity: 0, y: 2 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, delay: Math.min(delayStep, 0.2) }}
      className="grid gap-3 items-center border-b last:border-0 border-border/50 px-4 py-2.5"
      style={{ gridTemplateColumns: `clamp(140px, 22vw, 220px) repeat(${cols}, minmax(160px, 1fr))` }}
    >
      <div className="min-w-0">
        <div className="text-sm font-medium flex items-center gap-1.5 min-w-0">
          <span className="truncate">{row.label}</span>
          {row.direction !== "none" && (
            <span
              title={row.direction === "higher" ? "Higher is better" : "Lower is better"}
              className="shrink-0 text-[9px] uppercase tracking-wider text-muted-foreground"
            >
              {row.direction === "higher" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
            </span>
          )}
        </div>
        {row.hint && (
          <div className="text-[10px] text-muted-foreground flex items-center gap-1 mt-0.5">
            <Info className="h-2.5 w-2.5" />
            {row.hint}
          </div>
        )}
      </div>

      {cells.map((cell) => (
        <Cell
          key={cell.dealId}
          row={row}
          cell={cell}
          cells={cells}
          mode={mode}
          isWinner={winners.has(cell.dealId)}
          isLoser={losers.has(cell.dealId)}
          baselineCell={baseline ? cells.find((c) => c.dealId === baseline.id) ?? null : null}
        />
      ))}
    </motion.div>
  );
}

function Cell({
  row,
  cell,
  cells,
  mode,
  isWinner,
  isLoser,
  baselineCell,
}: {
  row: MetricRow;
  cell: CellValue;
  cells: CellValue[];
  mode: CompareMode;
  isWinner: boolean;
  isLoser: boolean;
  baselineCell: CellValue | null;
}) {
  // Normalized mode: show a 0-100% bar + value
  if (mode === "normalized" && row.direction !== "none") {
    const r = normalize(row, cell, cells);
    if (r == null) {
      return <span className="text-sm text-muted-foreground text-right">{formatValue(cell.raw, row.format)}</span>;
    }
    const pct = Math.max(0, Math.min(1, r)) * 100;
    return (
      <div className="min-w-0">
        <div className="text-sm text-right tabular-nums font-medium">{formatValue(cell.raw, row.format)}</div>
        <div className="mt-1 h-1 rounded-full bg-muted overflow-hidden">
          <motion.div
            className={cn(
              "h-full rounded-full",
              pct >= 80 ? "bg-success" : pct >= 40 ? "bg-primary" : "bg-warning",
            )}
            initial={{ width: 0 }}
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
          />
        </div>
      </div>
    );
  }

  // Delta mode: show the diff from baseline
  if (mode === "deltas" && baselineCell && row.direction !== "none" && cell.num != null && baselineCell.num != null) {
    if (cell.dealId === baselineCell.dealId) {
      return (
        <span className="text-sm text-right tabular-nums font-semibold text-primary">
          {formatValue(cell.raw, row.format)}
        </span>
      );
    }
    const diff = cell.num - baselineCell.num;
    const favorable = row.direction === "higher" ? diff > 0 : diff < 0;
    const color =
      diff === 0 ? "text-muted-foreground" : favorable ? "text-success" : "text-destructive";
    const formatted = formatDelta(diff, row.format);
    return (
      <div className="text-right tabular-nums leading-tight">
        <div className="text-sm font-medium">{formatValue(cell.raw, row.format)}</div>
        <div className={cn("text-[10px] font-semibold", color)}>
          {diff > 0 ? "+" : ""}
          {formatted}
        </div>
      </div>
    );
  }

  // Values (+ optional winners) mode
  const showHighlight = mode === "winners" || mode === "values";
  return (
    <div
      className={cn(
        "text-sm text-right tabular-nums font-medium rounded-md px-2 py-1 transition-colors",
        showHighlight && isWinner && "bg-success/10 text-success ring-1 ring-success/30",
        showHighlight && isLoser && "bg-destructive/10 text-destructive ring-1 ring-destructive/30",
      )}
    >
      <div className="flex items-center justify-end gap-1">
        {showHighlight && isWinner && <Crown className="h-3 w-3 opacity-70" />}
        <span>{formatValue(cell.raw, row.format)}</span>
      </div>
    </div>
  );
}

function formatDelta(diff: number, format: string): string {
  if (format === "money") return fmtMoney(Math.abs(diff));
  if (format === "percent") return `${Math.abs(diff).toFixed(1)}pp`;
  if (format === "multiple") return fmtMultiple(Math.abs(diff));
  if (format === "years") return `${Math.abs(diff)}y`;
  return Math.abs(diff).toLocaleString(undefined, { maximumFractionDigits: 2 });
}
