"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowUpRight, MapPin } from "lucide-react";
import { Card } from "@/components/ui/card";
import { ScoreQualityBadge } from "@/components/deal-detail/score-quality-badge";
import { cn, fmtMultiple, fmtMoney, fmtPct } from "@/lib/utils";
import type { DataQualityGate, DealQualitySummary, DealSummary, FieldProvenance } from "@/lib/types";

const STATUS_STYLES: Record<string, string> = {
  reviewing: "bg-muted/60 text-muted-foreground",
  interested: "bg-primary/15 text-primary ring-1 ring-primary/30",
  passed: "bg-destructive/15 text-destructive ring-1 ring-destructive/30",
  committed: "bg-success/15 text-success ring-1 ring-success/30",
  closed: "bg-chart-3/15 text-[hsl(var(--chart-3))] ring-1 ring-[hsl(var(--chart-3))/.3]",
};

type SummaryWithMetrics = DealSummary & {
  metrics?: {
    target_returns?: Record<string, unknown>;
    _provenance?: Record<string, FieldProvenance>;
  };
};

function ScoreRing({ value }: { value: number | null }) {
  if (value == null) {
    return (
      <div className="h-12 w-12 rounded-full border border-dashed border-border grid place-items-center text-muted-foreground text-[10px]">
        -
      </div>
    );
  }
  const pct = Math.max(0, Math.min(10, value)) / 10;
  const color = value >= 8 ? "hsl(var(--success))" : value >= 6 ? "hsl(var(--warning))" : "hsl(var(--destructive))";
  const circumference = 2 * Math.PI * 20;
  const offset = circumference * (1 - pct);

  return (
    <div className="relative h-12 w-12">
      <svg viewBox="0 0 48 48" className="h-12 w-12 -rotate-90">
        <circle
          cx="24"
          cy="24"
          r="20"
          fill="none"
          stroke="hsl(var(--border))"
          strokeWidth="3"
        />
        <motion.circle
          cx="24"
          cy="24"
          r="20"
          fill="none"
          stroke={color}
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
        />
      </svg>
      <div
        className="absolute inset-0 grid place-items-center text-[13px] font-semibold tabular-nums"
        style={{ color }}
      >
        {value.toFixed(1)}
      </div>
    </div>
  );
}

export function DealCard({ deal }: { deal: DealSummary }) {
  const locationBits = [deal.city, deal.state].filter(Boolean).join(", ") || deal.location || "";
  const qualityGate = getQualityGate(deal.quality) || deal.scores?.data_quality;
  const visibleScore = deal.overall_score ?? deal.scores?.provisional_overall ?? null;
  const targetIrr = pickReturnMetric(deal, ["target_returns.target_irr", "target_returns.net_irr"]) ?? deal.target_irr;
  const targetMultiple = pickReturnMetric(deal, ["target_returns.target_equity_multiple", "target_returns.net_equity_multiple"]) ?? deal.target_equity_multiple;

  return (
    <Link href={`/deals/${deal.id}`} className="block group outline-none">
      <Card
        elevated
        className="p-5 transition-all duration-200 hover:border-border group-hover:-translate-y-1 group-hover:shadow-[0_20px_60px_-30px_hsl(var(--primary)/.4)] group-focus-visible:ring-2 group-focus-visible:ring-ring"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h3 className="text-base font-semibold tracking-tight truncate">{deal.project_name}</h3>
            <div className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
              <MapPin className="h-3 w-3" />
              <span className="truncate">{locationBits || "-"}</span>
              {deal.developer_name && (
                <>
                  <span className="opacity-40">·</span>
                  <span className="truncate">{deal.developer_name}</span>
                </>
              )}
            </div>
          </div>
          <ScoreRing value={visibleScore} />
        </div>

        <div className="mt-5 grid grid-cols-3 gap-3">
          <Stat label="Target IRR" value={fmtPct(targetIrr)} />
          <Stat label="Multiple" value={fmtMultiple(targetMultiple)} />
          <Stat label="Min Invest" value={fmtMoney(deal.minimum_investment)} />
        </div>

        <div className="mt-5 flex items-center justify-between">
          <div className="flex min-w-0 items-center gap-2">
            <span
              className={cn(
                "px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wider font-medium",
                STATUS_STYLES[deal.status] ?? STATUS_STYLES.reviewing,
              )}
            >
              {deal.status}
            </span>
            <ScoreQualityBadge gate={qualityGate} size="sm" />
          </div>
          <ArrowUpRight className="h-4 w-4 text-muted-foreground group-hover:text-foreground group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform" />
        </div>
      </Card>
    </Link>
  );
}

function getQualityGate(quality: DealQualitySummary | DataQualityGate | undefined): DataQualityGate | undefined {
  if (!quality) return undefined;
  if ("stage" in quality) return quality;
  return quality.data_quality;
}

function pickReturnMetric(deal: DealSummary, paths: string[]): number | null {
  const extended = deal as SummaryWithMetrics;
  const metrics = extended.metrics;
  const returns = metrics?.target_returns ?? {};
  const provenance = metrics?._provenance ?? {};
  const candidates = paths
    .map((path) => ({ path, value: asNum(returns[path.split(".").at(-1) ?? path]), provenance: provenance[path] }))
    .filter((candidate) => candidate.value !== null);

  if (candidates.length === 0) return null;
  const clean = candidates.filter((candidate) => !isBadSource(candidate.provenance));
  const reviewed = clean.find((candidate) => candidate.provenance?.locked || ["manual", "confirmed", "calculated"].includes(String(candidate.provenance?.status ?? "")));
  return (reviewed ?? clean[0] ?? candidates[0]).value;
}

function isBadSource(provenance?: FieldProvenance): boolean {
  if (!provenance) return false;
  const status = String(provenance.status ?? "").toLowerCase();
  const conflictCount = Array.isArray(provenance.conflict) ? provenance.conflict.length : 0;
  return conflictCount > 1 || ["wrong", "missing", "unverifiable", "stale"].includes(status);
}

function asNum(value: unknown): number | null {
  if (typeof value === "number" && !Number.isNaN(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && !Number.isNaN(Number(value))) return Number(value);
  return null;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="text-sm font-semibold tabular-nums tracking-tight mt-1">{value}</div>
    </div>
  );
}
