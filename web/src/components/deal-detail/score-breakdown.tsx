"use client";

import { motion } from "framer-motion";
import { Card } from "@/components/ui/card";
import { ScoreQualityBadge } from "@/components/deal-detail/score-quality-badge";
import { cn } from "@/lib/utils";
import type { DealScores, ScoreCategory } from "@/lib/types";

const CATEGORIES: Array<{ key: keyof DealScores; label: string }> = [
  { key: "returns", label: "Returns" },
  { key: "market", label: "Market" },
  { key: "structure", label: "Structure" },
  { key: "risk", label: "Risk" },
  { key: "financials", label: "Financials" },
  { key: "underwriting", label: "Underwriting" },
  { key: "sponsor", label: "Sponsor" },
];

function scoreNoteParts(notes: string): string[] {
  return notes
    .split(";")
    .map(cleanScoreNote)
    .filter(Boolean)
    .slice(0, 4);
}

function cleanScoreNote(note: string): string {
  let text = note.trim();
  if (!text) return "";

  text = text
    .replace(/^Primary strategy: long-term hold$/i, "Long-term hold primary")
    .replace(/^Primary strategy: sale$/i, "Sale case primary")
    .replace(/^sale case treated as optional\/hypothetical$/i, "Sale case optional")
    .replace(/^Sale-case equity multiple/i, "Optional sale multiple")
    .replace(/^Equity Multiple/i, "Equity multiple")
    .replace(/^Cash-on-Cash/i, "Cash-on-cash")
    .replace(/^Optional sale scenario shown separately \(/i, "Optional sale: ")
    .replace(/\)$/g, "")
    .replace(/\s*->\s*\d+(?:\.\d+)?\/10/g, "");

  return text;
}

/**
 * Horizontal bar chart of the 7 scoring categories. Each row shows weight,
 * score, and the scorer's notes. The bar grows in on mount for a bit of
 * dashboard-y polish.
 */
export function ScoreBreakdown({ scores }: { scores: Partial<DealScores> }) {
  if (!scores || Object.keys(scores).length === 0) {
    return (
      <Card elevated className="p-8 text-center">
        <div className="text-sm font-medium">No scores yet</div>
        <div className="text-xs text-muted-foreground mt-1">
          Upload an offering memo and run AI scoring to see the breakdown.
        </div>
      </Card>
    );
  }

  const visibleOverall = typeof scores.overall === "number" ? scores.overall : scores.provisional_overall;

  return (
    <Card elevated className="p-6">
      <div className="flex items-start justify-between gap-4 mb-5">
        <div>
          <h3 className="text-base font-semibold tracking-tight">Score breakdown</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Weighted composite of 7 analyst categories.
          </p>
          <div className="mt-2">
            <ScoreQualityBadge gate={scores.data_quality} />
          </div>
        </div>
        {typeof visibleOverall === "number" && (
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
              {typeof scores.overall === "number" ? "Overall" : "Provisional"}
            </div>
            <div className="text-2xl font-semibold tabular-nums leading-none mt-1">
              {visibleOverall.toFixed(1)}
            </div>
          </div>
        )}
      </div>

      <div className="space-y-3.5">
        {CATEGORIES.map((c, i) => {
          const cat = scores[c.key] as ScoreCategory | undefined;
          if (!cat || typeof cat !== "object" || cat === null || !("score" in cat)) return null;
          const score = Math.max(0, Math.min(10, cat.score));
          const pct = score * 10;
          const barColor =
            score >= 8
              ? "bg-success"
              : score >= 6
                ? "bg-warning"
                : "bg-destructive";
          const notes = typeof cat.notes === "string" ? scoreNoteParts(cat.notes) : [];

          return (
            <div key={c.key}>
              <div className="flex items-center justify-between gap-2 mb-1.5">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{c.label}</span>
                  <span className="text-[10px] text-muted-foreground uppercase tracking-wider border border-border/70 rounded px-1.5 py-0.5">
                    {cat.weight}%
                  </span>
                </div>
                <span className="text-sm tabular-nums font-semibold">
                  {score.toFixed(1)}
                  <span className="text-muted-foreground text-xs font-normal">/10</span>
                </span>
              </div>
              <div className="relative h-1.5 rounded-full bg-muted overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${pct}%` }}
                  transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1], delay: 0.05 * i }}
                  className={cn("absolute inset-y-0 left-0 rounded-full", barColor)}
                />
              </div>
              {notes.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {notes.map((note) => (
                    <span
                      key={note}
                      className="rounded-full border border-border/70 bg-muted/45 px-2.5 py-1 text-[11px] font-medium leading-none text-muted-foreground"
                    >
                      {note}
                    </span>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}
