"use client";

import * as React from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import type { DealSummary } from "@/lib/types";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { CompareClient } from "@/components/compare/compare-client";
import { FadeIn } from "@/components/motion";

export function ComparePageClient() {
  const [deals, setDeals] = React.useState<DealSummary[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const loadDeals = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setDeals(await api.get<DealSummary[]>("/api/deals", { timeoutMs: 15_000 }));
    } catch (loadError) {
      setError((loadError as { detail?: string })?.detail ?? "Deals could not be loaded. Refresh the page to try again.");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void loadDeals();
  }, [loadDeals]);

  return (
    <div className="mx-auto max-w-[1400px] px-6 py-8 md:px-10 md:py-10">
      <FadeIn>
        <div className="mb-8">
          <div className="mb-2 text-[11px] uppercase tracking-[0.14em] text-muted-foreground">Tool</div>
          <h1 className="text-display tracking-tight">Compare deals</h1>
          <p className="mt-1.5 max-w-xl text-sm text-muted-foreground">
            Compare returns, leverage, risk, market, sponsor, and underwriting assumptions side by side.
          </p>
        </div>
      </FadeIn>

      {loading ? (
        <Card elevated className="flex min-h-48 items-center justify-center p-8 text-center">
          <div>
            <Loader2 className="mx-auto h-5 w-5 animate-spin text-primary" />
            <div className="mt-3 text-sm font-semibold text-foreground">Loading comparison data</div>
            <p className="mt-1 text-xs text-muted-foreground">This should only take a few seconds.</p>
          </div>
        </Card>
      ) : error ? (
        <Card elevated className="flex min-h-48 items-center justify-center p-8 text-center">
          <div>
            <div className="font-semibold text-destructive">Comparison data is unavailable</div>
            <p className="mt-1 max-w-md text-sm text-muted-foreground">{error}</p>
            <Button className="mt-5" variant="outline" onClick={() => void loadDeals()}>
              <RefreshCw className="h-4 w-4" />
              Try again
            </Button>
          </div>
        </Card>
      ) : (
        <CompareClient deals={deals} />
      )}
    </div>
  );
}
