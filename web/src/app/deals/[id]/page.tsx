import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import type { DealDetail } from "@/lib/types";
import { DealHero } from "@/components/deal-detail/hero";
import { DealTabs, type DealTabKey } from "@/components/deal-detail/deal-tabs";
import { OverviewTab } from "@/components/deal-detail/overview-tab";
import { MetricsTab } from "@/components/deal-detail/metrics-tab";
import { CashflowTab } from "@/components/deal-detail/cashflow-tab";
import { DocumentsPanel } from "@/components/deal-detail/documents-panel";
import { ChatPanel } from "@/components/deal-detail/chat-panel";

export const dynamic = "force-dynamic";

export default async function DealDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const dealId = Number(id);
  if (!Number.isFinite(dealId)) notFound();

  let deal: DealDetail;
  try {
    deal = await api.get<DealDetail>(`/api/deals/${dealId}`);
  } catch (e) {
    const err = e as { status?: number; detail?: string };
    if (err.status === 404) notFound();
    throw e;
  }

  const tab = (typeof sp.tab === "string" ? sp.tab : "overview") as DealTabKey;

  return (
    <div className="max-w-[1400px] mx-auto px-6 md:px-10 py-8 md:py-10">
      <DealHero deal={deal} />

      <div className="mt-8">
        <DealTabs
          defaultTab={tab}
          overview={<OverviewTab deal={deal} />}
          metrics={<MetricsTab deal={deal} />}
          cashflow={<CashflowTab dealId={deal.id} projectedIrr={deal.target_irr} />}
          documents={<DocumentsPanel dealId={deal.id} documents={deal.documents ?? []} />}
          chat={<ChatPanel dealId={deal.id} />}
        />
      </div>
    </div>
  );
}
