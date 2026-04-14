"use client";

import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { X, AlertCircle, AlertTriangle, CheckCircle2, Crown, ExternalLink } from "lucide-react";
import { cn, fmtPct, fmtMultiple } from "@/lib/utils";
import type { DealDetail } from "@/lib/types";

/**
 * Sticky card row at the top. One card per selected deal with:
 *   - project + sponsor + city/state
 *   - overall score (big colored number)
 *   - validation-flag chips (red/yellow/green counts)
 *   - "Overall winner" crown when the deal wins the most metric rows
 *   - quick stats (IRR / Multiple)
 *   - remove-from-comparison button
 *
 * Stays sticky below the page header so metrics always line up under their
 * deal even when scrolling a long preset.
 */
export function DealHeaderRow({
  deals,
  overallWins,
  onRemove,
  cols,
}: {
  deals: DealDetail[];
  overallWins: Record<number, number>;
  onRemove: (id: number) => void;
  cols: number;
}) {
  const mostWins = Math.max(0, ...Object.values(overallWins));

  return (
    <div
      className="sticky top-16 z-20 bg-background/85 backdrop-blur-md border-b border-border/60 -mx-6 md:-mx-10 px-6 md:px-10 py-3"
    >
      <div
        className="grid gap-3"
        style={{ gridTemplateColumns: `220px repeat(${cols}, minmax(0, 1fr))` }}
      >
        {/* Row label column spacer */}
        <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground self-end pl-1 pb-1">
          Deals compared
        </div>

        <AnimatePresence>
          {deals.map((deal) => {
            const flags = deal.metrics?.validation_flags ?? [];
            const counts = {
              red: flags.filter((f) => f.severity === "red").length,
              yellow: flags.filter((f) => f.severity === "yellow").length,
              green: flags.filter((f) => f.severity === "green").length,
            };
            const wins = overallWins[deal.id] ?? 0;
            const isOverallWinner = wins > 0 && wins === mostWins && Object.keys(overallWins).length > 1;

            return (
              <motion.div
                key={deal.id}
                layout
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.96 }}
                transition={{ duration: 0.2 }}
                className="relative min-w-0 rounded-xl border border-border/80 bg-card p-3"
              >
                {isOverallWinner && (
                  <div className="absolute -top-2 left-3 inline-flex items-center gap-1 px-2 h-5 rounded-full bg-success/20 text-success ring-1 ring-success/50 text-[10px] font-semibold uppercase tracking-wider">
                    <Crown className="h-3 w-3" />
                    Best overall · {wins} wins
                  </div>
                )}

                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <Link
                      href={`/deals/${deal.id}`}
                      className="text-sm font-semibold tracking-tight truncate hover:text-primary inline-flex items-center gap-1"
                    >
                      <span className="truncate">{deal.project_name}</span>
                      <ExternalLink className="h-3 w-3 shrink-0 opacity-60" />
                    </Link>
                    <div className="text-[11px] text-muted-foreground mt-0.5 truncate">
                      {[deal.city, deal.state].filter(Boolean).join(", ") || "—"}
                      {deal.developer_name && (
                        <>
                          <span className="mx-1 opacity-40">·</span>
                          <span className="truncate">{deal.developer_name}</span>
                        </>
                      )}
                    </div>
                  </div>
                  <button
                    onClick={() => onRemove(deal.id)}
                    aria-label="Remove from comparison"
                    className="p-1 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>

                {/* Score + stats */}
                <div className="mt-3 flex items-center justify-between gap-2">
                  <div className="tabular-nums">
                    <div className={cn("text-xl font-semibold leading-none", scoreColor(deal.overall_score))}>
                      {deal.overall_score != null ? deal.overall_score.toFixed(1) : "—"}
                    </div>
                    <div className="text-[9px] uppercase tracking-wider text-muted-foreground mt-1">Score</div>
                  </div>
                  <div className="text-right text-[11px] tabular-nums leading-tight">
                    <div>
                      <span className="text-muted-foreground">IRR </span>
                      <span className="font-medium">{fmtPct(deal.target_irr)}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Mult </span>
                      <span className="font-medium">{fmtMultiple(deal.target_equity_multiple)}</span>
                    </div>
                  </div>
                </div>

                {/* Validation chips */}
                {(counts.red + counts.yellow + counts.green) > 0 && (
                  <div className="mt-2 flex items-center gap-1">
                    {counts.red > 0 && (
                      <span className="inline-flex items-center gap-0.5 px-1.5 h-4 rounded-full bg-destructive/15 text-destructive text-[10px] font-medium tabular-nums">
                        <AlertCircle className="h-2.5 w-2.5" />
                        {counts.red}
                      </span>
                    )}
                    {counts.yellow > 0 && (
                      <span className="inline-flex items-center gap-0.5 px-1.5 h-4 rounded-full bg-warning/15 text-warning text-[10px] font-medium tabular-nums">
                        <AlertTriangle className="h-2.5 w-2.5" />
                        {counts.yellow}
                      </span>
                    )}
                    {counts.green > 0 && (
                      <span className="inline-flex items-center gap-0.5 px-1.5 h-4 rounded-full bg-success/15 text-success text-[10px] font-medium tabular-nums">
                        <CheckCircle2 className="h-2.5 w-2.5" />
                        {counts.green}
                      </span>
                    )}
                  </div>
                )}
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </div>
  );
}

function scoreColor(v: number | null): string {
  if (v == null) return "text-muted-foreground";
  if (v >= 8) return "text-success";
  if (v >= 6) return "text-warning";
  return "text-destructive";
}
