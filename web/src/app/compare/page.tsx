import { api } from "@/lib/api";
import type { DealSummary } from "@/lib/types";
import { Card } from "@/components/ui/card";
import { CompareClient } from "@/components/compare/compare-client";
import { FadeIn } from "@/components/motion";

export const dynamic = "force-dynamic";

export default async function ComparePage() {
  let deals: DealSummary[] = [];
  let error: string | null = null;
  try {
    deals = await api.get<DealSummary[]>("/api/deals");
  } catch (e) {
    error = (e as { detail?: string })?.detail ?? "Failed to load deals";
  }

  return (
    <div className="max-w-[1400px] mx-auto px-6 md:px-10 py-8 md:py-10">
      <FadeIn>
        <div className="mb-8">
          <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground mb-2">
            Tool
          </div>
          <h1 className="text-display tracking-tight">Compare deals</h1>
          <p className="text-sm text-muted-foreground mt-1.5 max-w-xl">
            Executive, Returns, Leverage, Risk, Market, Sponsor, Underwriting presets — or build your own. Highlight winners, show deltas vs a baseline, or normalize across the group.
          </p>
        </div>
      </FadeIn>

      {error ? (
        <Card elevated className="p-8 text-center">
          <div className="text-destructive font-medium">Couldn&apos;t load deals</div>
          <div className="text-sm text-muted-foreground mt-1">{error}</div>
        </Card>
      ) : (
        <CompareClient deals={deals} />
      )}
    </div>
  );
}
