"use client";

import * as React from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

type UsageTotals = {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
};

type UsageEvent = {
  id: number;
  operation: string;
  model: string;
  status: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
  duration_ms?: number | null;
  created_at?: string | null;
};

type UsageResponse = {
  deal_id: number | null;
  totals: UsageTotals;
  today: UsageTotals;
  by_operation: Record<string, UsageTotals>;
  events: UsageEvent[];
};

export function AiUsagePanel({ dealId }: { dealId: number }) {
  const [data, setData] = React.useState<UsageResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let alive = true;
    api.get<UsageResponse>(`/api/admin/ai-usage?deal_id=${dealId}&limit=50`)
      .then((res) => {
        if (!alive) return;
        setData(res);
        setError(null);
      })
      .catch((err) => {
        if (!alive) return;
        setError((err as { detail?: string })?.detail || "Could not load AI usage.");
      });
    return () => {
      alive = false;
    };
  }, [dealId]);

  if (error) {
    return (
      <div className="rounded-lg border border-border/80 bg-muted/25 p-3 text-xs text-muted-foreground">
        AI usage is not available yet: {error}
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-lg border border-border/80 bg-muted/25 p-3 text-xs text-muted-foreground">
        Loading AI usage...
      </div>
    );
  }

  const latest = data.events.slice(0, 4);
  const hasUsage = data.totals.calls > 0;
  const verifyCost = data.by_operation.verify?.estimated_cost_usd ?? 0;
  const extractCost = data.by_operation.extract?.estimated_cost_usd ?? 0;
  const dominantOperation = verifyCost > extractCost && verifyCost > 0 ? "verify" : extractCost > 0 ? "extract" : null;

  return (
    <div className="rounded-lg border border-border/80 bg-background p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold tracking-tight text-foreground">AI usage</div>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            Estimated Anthropic usage for this deal. Costs are based on saved token counts and configurable model pricing.
          </p>
        </div>
        <div className="rounded-lg border border-border/80 bg-muted/30 px-3 py-2 text-right">
          <div className="text-[10px] font-extrabold uppercase tracking-[0.12em] text-muted-foreground">Today</div>
          <div className="mt-0.5 text-lg font-extrabold tabular-nums text-foreground">{fmtUsd(data.today.estimated_cost_usd)}</div>
        </div>
      </div>

      {hasUsage ? (
        <>
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <UsageStat label="Total cost" value={fmtUsd(data.totals.estimated_cost_usd)} />
            <UsageStat label="AI calls" value={String(data.totals.calls)} />
            <UsageStat label="Input tokens" value={fmtTokens(data.totals.input_tokens)} />
            <UsageStat label="Output tokens" value={fmtTokens(data.totals.output_tokens)} />
          </div>

          {Object.keys(data.by_operation).length > 0 && (
            <div className="mt-4 flex flex-wrap gap-2">
              {Object.entries(data.by_operation).map(([operation, totals]) => (
                <span key={operation} className="rounded-full border border-border/80 bg-muted/30 px-2.5 py-1 text-xs text-muted-foreground">
                  <span className="font-semibold text-foreground">{operation}</span> · {totals.calls} call{totals.calls === 1 ? "" : "s"} · {fmtUsd(totals.estimated_cost_usd)}
                </span>
              ))}
            </div>
          )}

          {dominantOperation ? (
            <div className="mt-4 rounded-lg border border-primary/20 bg-primary/5 p-3 text-xs leading-relaxed text-muted-foreground">
              <span className="font-semibold text-foreground">Cost note: </span>
              {dominantOperation === "verify"
                ? "Most spend is source verification. Re-running unchanged documents should reuse cached source checks; upload or edit only when documents or values truly changed."
                : "Most spend is document reading. Unchanged uploaded files should reuse the prior extraction instead of paying to read them again."}
            </div>
          ) : null}

          {latest.length > 0 && (
            <div className="mt-4 overflow-hidden rounded-lg border border-border/70">
              {latest.map((event, index) => (
                <div
                  key={event.id}
                  className={cn(
                    "grid gap-2 px-3 py-2 text-xs sm:grid-cols-[7rem_1fr_auto]",
                    index > 0 && "border-t border-border/70",
                  )}
                >
                  <div className="font-semibold text-foreground">{event.operation}</div>
                  <div className="min-w-0 text-muted-foreground">
                    <span className="truncate">{event.model}</span>
                    <span className="mx-1">·</span>
                    <span>{fmtTokens(event.input_tokens)} in</span>
                    <span className="mx-1">/</span>
                    <span>{fmtTokens(event.output_tokens)} out</span>
                  </div>
                  <div className="font-semibold tabular-nums text-foreground">{fmtUsd(event.estimated_cost_usd)}</div>
                </div>
              ))}
            </div>
          )}
        </>
      ) : (
        <div className="mt-4 rounded-lg border border-dashed border-border/80 bg-muted/20 p-3 text-xs text-muted-foreground">
          No persisted AI usage has been recorded for this deal yet. The next document review will populate this panel.
        </div>
      )}
    </div>
  );
}

function UsageStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border/70 bg-card px-3 py-2">
      <div className="text-[10px] font-extrabold uppercase tracking-[0.12em] text-muted-foreground">{label}</div>
      <div className="mt-1 text-base font-extrabold tabular-nums text-foreground">{value}</div>
    </div>
  );
}

function fmtUsd(value: number | null | undefined): string {
  const n = typeof value === "number" && Number.isFinite(value) ? value : 0;
  if (n < 0.01 && n > 0) return "<$0.01";
  return n.toLocaleString(undefined, { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtTokens(value: number | null | undefined): string {
  const n = typeof value === "number" && Number.isFinite(value) ? value : 0;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}
