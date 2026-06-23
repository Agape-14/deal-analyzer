"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowUpRight, MapPin } from "lucide-react";
import { Card } from "@/components/ui/card";
import { ScoreQualityBadge } from "@/components/deal-detail/score-quality-badge";
import { useCurrentUser } from "@/lib/auth-client";
import { getHeadlineReturnMetrics } from "@/lib/return-metrics";
import { cn, fmtMultiple, fmtMoney, fmtPct } from "@/lib/utils";
import type { DataQualityGate, DealQualitySummary, DealSummary } from "@/lib/types";

const STATUS_STYLES: Record<string, string> = {
  reviewing: "bg-muted/60 text-muted-foreground",
  interested: "bg-primary/15 text-primary ring-1 ring-primary/30",
  passed: "bg-destructive/15 text-destructive ring-1 ring-destructive/30",
  committed: "bg-success/15 text-success ring-1 ring-success/30",
  closed: "bg-chart-3/15 text-[hsl(var(--chart-3))] ring-1 ring-[hsl(var(--chart-3))/.3]",
};

function ScoreRing({ value }: { value: number | null }) {
  if (value == null) {
    return (
      <div className="grid h-12 w-12 place-items-center rounded-full border border-dashed border-border text-[10px] text-muted-foreground">
        -
      </div>
    );
  }
  const pct = Math.max(0, Math.min(10, value)) / 10;
  const color = value >= 8 ? "hsl(var(--success))" : value >= 6 ? "hsl(var(--warning))" : "hsl(var(--destructive))";
  const circumference = 2 * Math.PI * 20;
  const offset = circumference * (1 - pct);

  return (
    <div className="relative h-12 w-12 shrink-0">
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
  const { isAnalyst } = useCurrentUser();
  const locationBits = [deal.city, deal.state].filter(Boolean).join(", ") || deal.location || "";
  const qualityGate = getQualityGate(deal.quality) || deal.scores?.data_quality;
  const visibleScore = deal.overall_score ?? deal.scores?.provisional_overall ?? null;
  const { headlineMultiple, primaryReturnLabel, primaryReturnValue } = getHeadlineReturnMetrics(deal);

  return (
    <Link href={`/deals/${deal.id}`} className="block h-full outline-none group">
      <Card
        elevated
        className="h-full p-5 transition-all duration-200 hover:border-border group-hover:-translate-y-1 group-hover:shadow-[0_20px_60px_-30px_hsl(var(--primary)/.4)] group-focus-visible:ring-2 group-focus-visible:ring-ring"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h3 className="truncate text-base font-semibold tracking-tight">{deal.project_name}</h3>
            <div className="mt-1 flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
              <MapPin className="h-3 w-3 shrink-0" />
              <span className="truncate">{locationBits || "-"}</span>
              {deal.developer_name && (
                <>
                  <span className="shrink-0 opacity-40">-</span>
                  <span className="truncate">{deal.developer_name}</span>
                </>
              )}
            </div>
          </div>
          <ScoreRing value={visibleScore} />
        </div>

        <div className="mt-5 grid grid-cols-3 gap-3">
          <Stat label={primaryReturnLabel} value={fmtPct(primaryReturnValue)} />
          <Stat label="Multiple" value={fmtMultiple(headlineMultiple)} />
          <Stat label="Min Invest" value={fmtMoney(deal.minimum_investment)} />
        </div>

        <div className="mt-5 flex min-h-7 flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider",
                STATUS_STYLES[deal.status] ?? STATUS_STYLES.reviewing,
              )}
            >
              {deal.status}
            </span>
            {isAnalyst && <ScoreQualityBadge gate={qualityGate} size="sm" />}
          </div>
          <ArrowUpRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-foreground" />
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

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold tabular-nums tracking-tight">{value}</div>
    </div>
  );
}
