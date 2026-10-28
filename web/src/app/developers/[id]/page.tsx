import { notFound, redirect } from "next/navigation";
import { api } from "@/lib/api";
import type { Developer, DealSummary, Investment } from "@/lib/types";
import { DeveloperDetailView } from "@/components/developers/dev-detail-view";
import { DeveloperDrawer } from "@/components/developers/dev-edit-drawer";
import Link from "next/link";

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
    if ((e as { status?: number }).status === 401) redirect("/login");
    if ((e as { status?: number }).status === 404) notFound();
    throw e;
  }

  const activity = await Promise.allSettled([
    api.get<DealSummary[]>("/api/deals"),
    api.get<Investment[]>("/api/investments/"),
  ]);
  if (activity.some(result => result.status === "rejected")) {
    if (activity.some(result => result.status === "rejected" && result.reason?.status === 401)) redirect("/login");
    return <div className="p-6 space-y-4"><h1 className="text-2xl font-semibold">{developer.name}</h1><div role="alert" className="rounded-xl border border-warning/40 p-5"><p>Sponsor activity is unavailable. Deal counts, positions and invested capital could not be loaded.</p><Link className="mt-3 inline-block underline" href={`/developers/${developer.id}`}>Retry sponsor activity</Link></div></div>;
  }
  const deals = activity[0].status === "fulfilled" ? activity[0].value : [];
  const investments = activity[1].status === "fulfilled" ? activity[1].value : [];

  const ownDeals = deals.filter((d) => d.developer_id === developer.id);
  const ownInvestments = investments.filter(
    (i) => i.developer_id === developer.id || (i.deal_id != null && ownDeals.some(d => d.id === i.deal_id)),
  );

  return (
    <>
      <DeveloperDetailView developer={developer} deals={ownDeals} investments={ownInvestments} />
      <DeveloperDrawer />
    </>
  );
}
