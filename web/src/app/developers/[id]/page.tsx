import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import type { Developer, DealSummary, Investment } from "@/lib/types";
import { DeveloperDetailView } from "@/components/developers/dev-detail-view";
import { DeveloperDrawer } from "@/components/developers/dev-edit-drawer";

export const dynamic = "force-dynamic";

/** Developer detail. The backend detail endpoint gives us a condensed deals
 * array (id + scores). For richer stats we also pull the full deals list
 * and the full investments list and filter by sponsor name client-side. */
export default async function DeveloperDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const devId = Number(id);
  if (!Number.isFinite(devId)) notFound();

  let developer: Developer;
  try {
    developer = await api.get<Developer>(`/api/developers/${devId}`);
  } catch (e) {
    if ((e as { status?: number }).status === 404) notFound();
    throw e;
  }

  const [deals, investments] = await Promise.all([
    api.get<DealSummary[]>("/api/deals").catch(() => [] as DealSummary[]),
    api.get<Investment[]>("/api/investments/").catch(() => [] as Investment[]),
  ]);

  const ownDeals = deals.filter((d) => d.developer_id === developer.id);
  const ownInvestments = investments.filter(
    (i) => i.sponsor_name && i.sponsor_name.trim().toLowerCase() === developer.name.trim().toLowerCase(),
  );

  return (
    <>
      <DeveloperDetailView developer={developer} deals={ownDeals} investments={ownInvestments} />
      <DeveloperDrawer />
    </>
  );
}
