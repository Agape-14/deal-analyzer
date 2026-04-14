import { FileSpreadsheet, FileDown } from "lucide-react";
import { api } from "@/lib/api";
import type { Investment, PortfolioAnalytics } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { PortfolioClient } from "@/components/portfolio/portfolio-client";
import { NewInvestmentDrawer } from "@/components/portfolio/new-investment-drawer";
import { AddInvestmentButton, EmptyPortfolio } from "@/components/portfolio/actions";
import { FadeIn } from "@/components/motion";

export const dynamic = "force-dynamic";

export default async function PortfolioPage() {
  let investments: Investment[] = [];
  let analytics: PortfolioAnalytics | null = null;
  let error: string | null = null;

  try {
    const [invList, analyticsResp] = await Promise.all([
      api.get<Investment[]>("/api/investments/"),
      api.get<PortfolioAnalytics>("/api/investments/portfolio/analytics"),
    ]);
    investments = invList;
    analytics = analyticsResp;
  } catch (e) {
    error = (e as { detail?: string })?.detail ?? "Failed to load portfolio";
  }

  return (
    <div className="max-w-[1400px] mx-auto px-6 md:px-10 py-8 md:py-10">
      <FadeIn>
        <div className="flex items-end justify-between gap-4 flex-wrap mb-8">
          <div>
            <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground mb-2">
              Overview
            </div>
            <h1 className="text-display tracking-tight">Portfolio</h1>
            <p className="text-sm text-muted-foreground mt-1.5 max-w-xl">
              Live IRR, DPI, and multiple across your entire investment book.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" asChild>
              <a href="/api/reports/portfolio/excel" target="_blank" rel="noreferrer">
                <FileSpreadsheet className="h-4 w-4" />
                Excel
              </a>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <a href="/api/reports/portfolio/quarterly/pdf" target="_blank" rel="noreferrer">
                <FileDown className="h-4 w-4" />
                Quarterly PDF
              </a>
            </Button>
            <AddInvestmentButton />
          </div>
        </div>
      </FadeIn>

      {error ? (
        <Card elevated className="p-8 text-center">
          <div className="text-destructive font-medium">Couldn&apos;t load portfolio</div>
          <div className="text-sm text-muted-foreground mt-1">{error}</div>
        </Card>
      ) : !analytics || investments.length === 0 ? (
        <EmptyPortfolio />
      ) : (
        <PortfolioClient investments={investments} analytics={analytics} />
      )}

      {/* Drawer mounts once; opens via custom events from any button. */}
      <NewInvestmentDrawer />
    </div>
  );
}
