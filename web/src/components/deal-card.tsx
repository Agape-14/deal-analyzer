"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowUpRight, MapPin } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn, fmtMultiple, fmtMoney, fmtPct } from "@/lib/utils";
import type { DealSummary } from "@/lib/types";

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
      <div className="h-12 w-12 rounded-full border border-dashed border-border grid place-items-center text-muted-foreground text-[10px]">
        —
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
              <span className="truncate">{locationBits || "—"}</span>
              {deal.developer_name && (
                <>
                  <span className="opacity-40">·</span>
                  <span className="truncate">{deal.developer_name}</span>
                </>
              )}
            </div>
          </div>
          <ScoreRing value={deal.overall_score} />
        </div>

        <div className="mt-5 grid grid-cols-3 gap-3">
          <Stat label="Target IRR" value={fmtPct(deal.target_irr)} />
          <Stat label="Multiple" value={fmtMultiple(deal.target_equity_multiple)} />
          <Stat label="Min Invest" value={fmtMoney(deal.minimum_investment)} />
        </div>

        <div className="mt-5 flex items-center justify-between">
          <span
            className={cn(
              "px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wider font-medium",
              STATUS_STYLES[deal.status] ?? STATUS_STYLES.reviewing,
            )}
          >
            {deal.status}
          </span>
          <ArrowUpRight className="h-4 w-4 text-muted-foreground group-hover:text-foreground group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform" />
        </div>
      </Card>
    </Link>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="text-sm font-semibold tabular-nums tracking-tight mt-1">{value}</div>
    </div>
  );
}
