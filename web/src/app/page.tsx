import { api } from "@/lib/api";
import type { DealSummary } from "@/lib/types";
import { DealGrid } from "@/components/deal-grid";
import { StatCard } from "@/components/stat-card";
import { FadeIn } from "@/components/motion";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PipelineWidgets, type PipelineSummary } from "@/components/pipeline-widgets";
import { fmtMoney } from "@/lib/utils";
import Link from "next/link";
import { LayoutDashboard, Sparkles } from "lucide-react";

export const dynamic = "force-dynamic";

export default async function Home() {
  let deals: DealSummary[] = [];
  let pipeline: PipelineSummary | null = null;
  let error: string | null = null;
  try {
    [deals, pipeline] = await Promise.all([
      api.get<DealSummary[]>("/api/deals"),
      api.get<PipelineSummary>("/api/deals/pipeline/summary").catch(() => null),
    ]);
  } catch (e) {
    error = (e as { detail?: string }).detail ?? "Failed to load deals";
  }

  const totalValue = deals.reduce((a, d) => a + (d.minimum_investment ?? 0), 0);

  return (
    <div className="max-w-[1400px] mx-auto px-6 md:px-10 py-8 md:py-12">
      {/* Hero */}
      <FadeIn>
        <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4 mb-8">
          <div>
            <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground mb-2">
              Overview
            </div>
            <h1 className="text-display tracking-tight">Deal Pipeline</h1>
            <p className="text-sm text-muted-foreground mt-1.5 max-w-xl">
              {deals.length
                ? `${deals.length} deal${deals.length === 1 ? "" : "s"} across your sponsors. Upload offering memos to score them automatically.`
                : "Upload your first offering memo to start analyzing deals."}
            </p>
          </div>
        </div>
      </FadeIn>

      {/* Pipeline widgets: velocity, win rate, capital, aging */}
      {pipeline ? (
        <PipelineWidgets summary={pipeline} />
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-4 mb-10">
          <StatCard label="Total Deals" value={deals.length} />
          <StatCard label="Reviewing" value={deals.filter((d) => d.status === "reviewing").length} />
          <StatCard label="Committed" value={deals.filter((d) => d.status === "committed").length} accent="primary" />
          <StatCard label="Avg Score" value={0} format="score" />
        </div>
      )}

      {/* Deals */}
      {error ? (
        <Card elevated className="p-8 text-center">
          <div className="text-destructive font-medium">Couldn&apos;t load deals</div>
          <div className="text-sm text-muted-foreground mt-1">{error}</div>
          <div className="text-xs text-muted-foreground mt-4">
            Is the FastAPI backend running on <code className="font-mono">http://127.0.0.1:8000</code>?
          </div>
        </Card>
      ) : deals.length === 0 ? (
        <EmptyState />
      ) : (
        <DealGrid deals={deals} />
      )}

      <FadeIn delay={0.3}>
        <div className="mt-16 flex items-center gap-2 text-[11px] text-muted-foreground">
          <Sparkles className="h-3 w-3" />
          Total min-investment exposure:{" "}
          <span className="tabular-nums text-foreground font-medium">{fmtMoney(totalValue)}</span>
        </div>
      </FadeIn>
    </div>
  );
}

function EmptyState() {
  return (
    <Card elevated className="p-12 text-center relative overflow-hidden">
      <div className="absolute inset-0 bg-gradient-to-b from-primary/5 to-transparent" />
      <div className="relative">
        <div className="inline-flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 ring-1 ring-primary/20 mb-4">
          <LayoutDashboard className="h-5 w-5 text-primary" />
        </div>
        <h3 className="text-lg font-semibold tracking-tight">No deals yet</h3>
        <p className="text-sm text-muted-foreground mt-1.5 max-w-md mx-auto">
          Create a deal and upload offering memorandums to get automated scoring, validation, and risk analysis.
        </p>
        <Button asChild className="mt-6">
          <Link href="/?new=1" scroll={false}>
            Create your first deal
          </Link>
        </Button>
      </div>
    </Card>
  );
}
