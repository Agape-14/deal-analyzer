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
export function ScoreBreakdown({
  scores,
  viewerMode = false,
}: {
  scores: Partial<DealScores>;
  viewerMode?: boolean;
}) {
  if (!scores || Object.keys(scores).length === 0) {
    return (
      <Card elevated className="p-8 text-center">
        <div className="text-sm font-medium">No scores yet</div>
        <div className="text-xs text-muted-foreground mt-1">
          Category scores appear as their source-supported inputs become available.
        </div>
      </Card>
    );
  }

  const visibleOverall = typeof scores.overall === "number" ? scores.overall : scores.provisional_overall;
  const supportedCount = CATEGORIES.filter(category => typeof (scores[category.key] as ScoreCategory | undefined)?.score === "number").length;

  return (
    <Card elevated className="p-6">
      <div className="flex items-start justify-between gap-4 mb-5">
        <div>
          <h3 className="text-base font-semibold tracking-tight">{viewerMode ? "Decision drivers" : "Score breakdown"}</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            {viewerMode
              ? "A simplified view of what is helping or hurting this deal."
              : `${supportedCount} of 7 categories have source-supported inputs.`}
          </p>
          {!viewerMode && (
            <div className="mt-2">
              <ScoreQualityBadge gate={scores.data_quality} />
            </div>
          )}
        </div>
        {typeof visibleOverall === "number" && (
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
              {typeof scores.overall === "number" ? "Overall" : "Partial composite"}
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
          const score = typeof cat.score === "number" ? Math.max(0, Math.min(10, cat.score)) : null;
          if (score === null) return <div key={c.key} className="border-b border-border/50 pb-3 last:border-0">
            <div className="flex items-center justify-between gap-2"><span className="text-sm font-medium">{c.label}</span><span className="text-xs text-muted-foreground">Needs source inputs</span></div>
            {cat.notes && <p className="mt-1 text-xs text-muted-foreground">{cat.notes}</p>}
          </div>;
          const pct = score * 10;
          const barColor =
            score >= 8
              ? "bg-success"
              : score >= 6
                ? "bg-warning"
                : "bg-destructive";
          const notes = typeof cat.notes === "string" ? scoreNoteParts(cat.notes).slice(0, viewerMode ? 1 : 4) : [];

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
