"use client";

import * as React from "react";
import { PortfolioHero } from "@/components/portfolio/hero";
import { PerformanceChart } from "@/components/portfolio/performance-chart";
import { AllocationBreakdown } from "@/components/portfolio/allocation-breakdown";
import { PositionGrid } from "@/components/portfolio/position-grid";
import { PerformersStrip } from "@/components/portfolio/performers-strip";
import { DistributionModal } from "@/components/portfolio/distribution-modal";
import { ExitModal } from "@/components/portfolio/exit-modal";
import { FadeIn } from "@/components/motion";
import type { Investment, PortfolioAnalytics } from "@/lib/types";

/**
 * Stateful wrapper that owns the currently-open distribution/exit modal.
 * Keeps the server component clean and makes the modals available to every
 * position card via props.
 */
export function PortfolioClient({
  investments,
  analytics,
}: {
  investments: Investment[];
  analytics: PortfolioAnalytics;
}) {
  const [distInv, setDistInv] = React.useState<Investment | null>(null);
  const [exitInv, setExitInv] = React.useState<Investment | null>(null);

  const performanceMap = React.useMemo(() => {
    const m: Record<number, (typeof analytics.per_investment)[number]> = {};
    for (const p of analytics.per_investment ?? []) m[p.investment_id] = p;
    return m;
  }, [analytics]);

  return (
    <>
      <FadeIn>
        <PortfolioHero analytics={analytics} />
      </FadeIn>

      <div className="mt-8">
        <PerformanceChart analytics={analytics} />
      </div>

      <div className="mt-6">
        <AllocationBreakdown analytics={analytics} />
      </div>

      <div className="mt-6">
        <PerformersStrip
          top={analytics.top_performers ?? []}
          bottom={analytics.bottom_performers ?? []}
          investments={investments}
        />
      </div>

      <div className="mt-10">
        <div className="mb-5">
          <h2 className="text-lg font-semibold tracking-tight">Positions</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Per-investment breakdown with per-deal IRR, multiple, and cash history.
          </p>
        </div>
        <PositionGrid
          investments={investments}
          performance={performanceMap}
          onAddDistribution={(inv) => setDistInv(inv)}
          onMarkExit={(inv) => setExitInv(inv)}
        />
      </div>

      <DistributionModal
        investment={distInv}
        open={distInv !== null}
        onOpenChange={(o) => !o && setDistInv(null)}
      />
      <ExitModal investment={exitInv} open={exitInv !== null} onOpenChange={(o) => !o && setExitInv(null)} />
    </>
  );
}
