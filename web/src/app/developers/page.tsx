import { Plus } from "lucide-react";
import { api } from "@/lib/api";
import type { Developer, DealSummary } from "@/lib/types";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { DeveloperGrid } from "@/components/developers/dev-grid";
import { DeveloperDrawer } from "@/components/developers/dev-edit-drawer";
import { AddDeveloperButton } from "@/components/developers/actions";
import { FadeIn } from "@/components/motion";
import { Building2 } from "lucide-react";

export const dynamic = "force-dynamic";

export default async function DevelopersPage() {
  let developers: Developer[] = [];
  let deals: DealSummary[] = [];
  let error: string | null = null;

  try {
    const [dev, d] = await Promise.all([
      api.get<Developer[]>("/api/developers"),
      api.get<DealSummary[]>("/api/deals"),
    ]);
    developers = dev;
    deals = d;
  } catch (e) {
    error = (e as { detail?: string })?.detail ?? "Failed to load developers";
  }

  return (
    <div className="max-w-[1400px] mx-auto px-6 md:px-10 py-8 md:py-10">
      <FadeIn>
        <div className="flex items-end justify-between gap-4 flex-wrap mb-8">
          <div>
            <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground mb-2">
              Overview
            </div>
            <h1 className="text-display tracking-tight">Developers</h1>
            <p className="text-sm text-muted-foreground mt-1.5 max-w-xl">
              Sponsor book with aggregated per-sponsor deal stats and track record.
            </p>
          </div>
          <AddDeveloperButton />
        </div>
      </FadeIn>

      {error ? (
        <Card elevated className="p-8 text-center">
          <div className="text-destructive font-medium">Couldn&apos;t load developers</div>
          <div className="text-sm text-muted-foreground mt-1">{error}</div>
        </Card>
      ) : developers.length === 0 ? (
        <EmptyState />
      ) : (
        <DeveloperGrid developers={developers} deals={deals} />
      )}

      <DeveloperDrawer />
    </div>
  );
}

function EmptyState() {
  return (
    <Card elevated className="p-12 text-center relative overflow-hidden">
      <div className="absolute inset-0 bg-gradient-to-b from-primary/5 to-transparent" />
      <div className="relative">
        <div className="inline-flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 ring-1 ring-primary/20 mb-4">
          <Building2 className="h-5 w-5 text-primary" />
        </div>
        <h3 className="text-lg font-semibold tracking-tight">No sponsors yet</h3>
        <p className="text-sm text-muted-foreground mt-1.5 max-w-md mx-auto">
          Add sponsors so deals can be linked to them — you&apos;ll see per-sponsor track record and portfolio stats here.
        </p>
        <div className="mt-6">
          <AddDeveloperButton variant="default" />
        </div>
      </div>
    </Card>
  );
}
