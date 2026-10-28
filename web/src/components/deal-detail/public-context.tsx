"use client";

import * as React from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";

type Observation = { metric: string; label: string; value: number | null; unit: string; margin_of_error: number | null; observed_period: string; source_url: string; geography_name: string; geography_level: string; geography_id: string; retrieved_at: string; publication_date: string | null; confidence_level: string };
type Context = { status: string; message: string; observations: Observation[]; asset_guidance: string; research_url: string; profile_supported: boolean };

export function PublicContext({ dealId }: { dealId: number }) {
  const [data, setData] = React.useState<Context | null>(null);
  const [error, setError] = React.useState(false);
  const [retry, reload] = React.useReducer(n => n + 1, 0);
  React.useEffect(() => {
    let active = true;
    setError(false);
    api.get<Context>(`/api/deals/${dealId}/public-context`).then(value => { if (active) setData(value); }).catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [dealId, retry]);
  return <Card className="p-4"><div className="flex justify-between gap-3"><h2 className="font-semibold text-sm">Public area context</h2><button className="text-xs underline shrink-0" onClick={reload}>Refresh context</button></div>
    {error && <p role="alert" className="mt-2 text-sm text-warning">Public context is unavailable. Retry to refresh. {data ? "Showing the previous retrieval below." : ""}</p>}
    {!data ? <p className="mt-2 text-xs text-muted-foreground">{error ? "Accepted deal facts remain available." : "Loading free public statistics…"}</p> : <>
      <p className="mt-2 text-xs text-muted-foreground">{data.message}</p>
      <div className="mt-3 grid sm:grid-cols-2 gap-3">{data.observations.map(o => <div key={o.metric} className="rounded-lg border p-3"><p className="text-xs text-muted-foreground">{o.label}</p><p className="mt-1 font-semibold">{o.value == null ? "Unavailable / suppressed" : o.metric === "median_household_income" ? `$${o.value.toLocaleString()}` : o.value.toLocaleString()}</p><p className="mt-1 text-xs text-muted-foreground">{o.unit} · {o.observed_period} · {o.geography_name} ({o.geography_level})</p><details className="mt-2 text-xs text-muted-foreground"><summary className="cursor-pointer">Source, uncertainty and freshness</summary><p className="mt-2">Margin of error: {o.margin_of_error?.toLocaleString() ?? "unavailable"} at {o.confidence_level} confidence. Geography: {o.geography_id}. Retrieved {o.retrieved_at?.slice(0, 10)}. Published: {o.publication_date ?? "date unavailable"}.</p><a href={o.source_url} target="_blank" rel="noreferrer" className="underline">Census source query</a></details></div>)}</div>
      <details className="mt-3 text-xs text-muted-foreground"><summary className="cursor-pointer">Asset-specific evidence still needed</summary><p className="mt-2">{data.asset_guidance}. Population and income describe the area; they do not establish property rents, vacancy or future performance.</p><a href={data.research_url} target="_blank" rel="noreferrer" className="mt-2 inline-block underline">Find dated market sources</a></details>
    </>}
  </Card>;
}
