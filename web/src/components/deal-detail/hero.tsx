"use client";

import Link from "next/link";
import { ArrowLeft, MapPin, Building2, Sparkles, FileDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BigScoreRing } from "@/components/deal-detail/score-ring";
import { FadeIn } from "@/components/motion";
import { cn, fmtMoney, fmtMultiple, fmtPct } from "@/lib/utils";
import type { DealDetail } from "@/lib/types";

const STATUS_STYLES: Record<string, string> = {
  reviewing: "bg-muted/60 text-muted-foreground",
  interested: "bg-primary/15 text-primary ring-1 ring-primary/30",
  passed: "bg-destructive/15 text-destructive ring-1 ring-destructive/30",
  committed: "bg-success/15 text-success ring-1 ring-success/30",
  closed: "bg-chart-3/15 text-[hsl(var(--chart-3))] ring-1 ring-[hsl(var(--chart-3))/.3]",
};

export function DealHero({ deal }: { deal: DealDetail }) {
  const locationBits = [deal.city, deal.state].filter(Boolean).join(", ") || deal.location;

  return (
    <FadeIn>
      <div className="relative">
        {/* Back nav */}
        <div className="mb-5">
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            All deals
          </Link>
        </div>

        <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-8">
          {/* Title block */}
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.14em] text-muted-foreground mb-2">
              <span>{deal.property_type || "Investment"}</span>
              <span className="opacity-40">·</span>
              <span
                className={cn(
                  "px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wider font-medium",
                  STATUS_STYLES[deal.status] ?? STATUS_STYLES.reviewing,
                )}
              >
                {deal.status}
              </span>
            </div>

            <h1 className="text-display-lg tracking-tight">{deal.project_name}</h1>

            <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-muted-foreground">
              {locationBits && (
                <span className="inline-flex items-center gap-1.5">
                  <MapPin className="h-4 w-4" />
                  {locationBits}
                </span>
              )}
              {deal.developer_name && (
                <span className="inline-flex items-center gap-1.5">
                  <Building2 className="h-4 w-4" />
                  {deal.developer_name}
                </span>
              )}
            </div>

            {/* Key metrics row */}
            <div className="mt-6 grid grid-cols-2 sm:grid-cols-4 gap-6">
              <Metric label="Target IRR" value={fmtPct(deal.target_irr)} />
              <Metric label="Equity Multiple" value={fmtMultiple(deal.target_equity_multiple)} />
              <Metric label="Min Investment" value={fmtMoney(deal.minimum_investment)} />
              <Metric label="Documents" value={String(deal.documents?.length ?? 0)} />
            </div>
          </div>

          {/* Score + actions */}
          <div className="flex flex-col items-center lg:items-end gap-4">
            {/* 96px ring on phones, 128px on tablet+ */}
            <div className="sm:hidden">
              <BigScoreRing value={deal.overall_score} size={96} />
            </div>
            <div className="hidden sm:block">
              <BigScoreRing value={deal.overall_score} size={128} />
            </div>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="secondary">
                <Sparkles className="h-4 w-4" />
                Re-score
              </Button>
              <Button size="sm" variant="outline" asChild>
                <a href={`/api/reports/deal/${deal.id}/pdf`} target="_blank" rel="noreferrer">
                  <FileDown className="h-4 w-4" />
                  Export PDF
                </a>
              </Button>
            </div>
          </div>
        </div>
      </div>
    </FadeIn>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">{label}</div>
      <div className="text-xl font-semibold tabular-nums tracking-tight mt-1.5">{value}</div>
    </div>
  );
}
