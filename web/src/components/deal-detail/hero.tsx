"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, MapPin, Building2, Sparkles, FileDown, Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { BigScoreRing } from "@/components/deal-detail/score-ring";
import { ScoreQualityBadge } from "@/components/deal-detail/score-quality-badge";
import { FadeIn } from "@/components/motion";
import { api } from "@/lib/api";
import { cn, fmtMoney, fmtMultiple, fmtPct } from "@/lib/utils";
import type { DealDetail, FieldProvenance } from "@/lib/types";

const STATUS_STYLES: Record<string, string> = {
  reviewing: "bg-muted/60 text-muted-foreground",
  interested: "bg-primary/15 text-primary ring-1 ring-primary/30",
  passed: "bg-destructive/15 text-destructive ring-1 ring-destructive/30",
  committed: "bg-success/15 text-success ring-1 ring-success/30",
  closed: "bg-chart-3/15 text-[hsl(var(--chart-3))] ring-1 ring-[hsl(var(--chart-3))/.3]",
};

type ProvenanceMap = Record<string, FieldProvenance | undefined>;

export function DealHero({ deal }: { deal: DealDetail }) {
  const router = useRouter();
  const [scoring, setScoring] = React.useState(false);
  const [pipelineRunning, setPipelineRunning] = React.useState(false);
  const locationBits = [deal.city, deal.state].filter(Boolean).join(", ") || deal.location;
  const visibleScore = deal.overall_score ?? deal.scores?.provisional_overall ?? null;
  const metrics = deal.metrics ?? {};
  const tr = (metrics.target_returns ?? {}) as Record<string, unknown>;
  const provenance = (metrics._provenance ?? {}) as ProvenanceMap;
  const headlineIrr = pickTrustedNumber(tr, provenance, ["target_returns.target_irr", "target_returns.net_irr"]) ?? deal.target_irr;
  const headlineMultiple = pickTrustedNumber(tr, provenance, ["target_returns.target_equity_multiple", "target_returns.net_equity_multiple"]) ?? deal.target_equity_multiple;

  async function runPipeline() {
    setPipelineRunning(true);
    try {
      await api.post(`/api/deals/${deal.id}/extract`);
      toast.success("Full pipeline started", {
        description: "Documents will be re-extracted, verified, math-checked, and scored automatically.",
        duration: 6000,
      });
      router.refresh();
    } catch (e) {
      toast.error("Could not start pipeline", { description: (e as { detail?: string })?.detail });
    } finally {
      setPipelineRunning(false);
    }
  }

  async function runScore() {
    setScoring(true);
    try {
      await api.post(`/api/deals/${deal.id}/score`);
      toast.success("Score recalculated", {
        description: "This used the metrics already extracted into the database.",
      });
      router.refresh();
    } catch (e) {
      toast.error("Could not recalculate score", { description: (e as { detail?: string })?.detail });
    } finally {
      setScoring(false);
    }
  }

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
              <Metric label="Target IRR" value={fmtPct(headlineIrr)} />
              <Metric label="Equity Multiple" value={fmtMultiple(headlineMultiple)} />
              <Metric label="Min Investment" value={fmtMoney(deal.minimum_investment)} />
              <Metric label="Documents" value={String(deal.documents?.length ?? 0)} />
            </div>
          </div>

          {/* Score + actions */}
          <div className="flex flex-col items-center lg:items-end gap-4">
            {/* 96px ring on phones, 128px on tablet+ */}
            <div className="sm:hidden">
              <BigScoreRing value={visibleScore} size={96} />
            </div>
            <div className="hidden sm:block">
              <BigScoreRing value={visibleScore} size={128} />
            </div>
            <ScoreQualityBadge gate={deal.scores?.data_quality} />
            <div className="flex flex-wrap items-center justify-center lg:justify-end gap-2 max-w-sm">
              <Button size="sm" onClick={runPipeline} disabled={pipelineRunning || scoring}>
                {pipelineRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                {pipelineRunning ? "Starting..." : "Re-run pipeline"}
              </Button>
              <Button size="sm" variant="secondary" onClick={runScore} disabled={scoring || pipelineRunning}>
                {scoring ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                {scoring ? "Calculating..." : "Recalculate score"}
              </Button>
              <Button size="sm" variant="outline" asChild>
                <a href={`/api/reports/deal/${deal.id}/pdf`} target="_blank" rel="noreferrer">
                  <FileDown className="h-4 w-4" />
                  Export PDF
                </a>
              </Button>
            </div>
            <p className="max-w-sm text-center lg:text-right text-[11px] leading-relaxed text-muted-foreground">
              Re-run pipeline reads all uploaded documents again. Recalculate score only uses already-extracted metrics.
            </p>
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

function pickTrustedNumber(block: Record<string, unknown>, provenance: ProvenanceMap, paths: string[]): number | null {
  const candidates = paths
    .map((path) => ({ path, value: asNum(block[path.split(".").at(-1) ?? path]), provenance: provenance[path] }))
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

function asNum(v: unknown): number | null {
  if (typeof v === "number" && !Number.isNaN(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v))) return Number(v);
  return null;
}
