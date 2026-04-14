"use client";

import { Card } from "@/components/ui/card";
import { ScoreBreakdown } from "@/components/deal-detail/score-breakdown";
import { ValidationFlagsPanel } from "@/components/deal-detail/validation-flags";
import { MetricsSection } from "@/components/deal-detail/metrics-section";
import { QualityPanel } from "@/components/deal-detail/quality-panel";
import type { DealDetail } from "@/lib/types";
import { fmtMoney, fmtMultiple, fmtPct } from "@/lib/utils";

const HERO_KEYS = [
  "target_irr",
  "target_equity_multiple",
  "target_cash_on_cash",
  "hold_period_years",
  "preferred_return",
  "ltv",
] as const;

export function OverviewTab({ deal }: { deal: DealDetail }) {
  const tr = (deal.metrics?.target_returns ?? {}) as Record<string, unknown>;
  const ds = (deal.metrics?.deal_structure ?? {}) as Record<string, unknown>;

  const snapshot = [
    { key: "target_irr", label: "Target IRR", value: fmtPct(asNum(tr.target_irr), 1) },
    { key: "target_equity_multiple", label: "Equity Multiple", value: fmtMultiple(asNum(tr.target_equity_multiple)) },
    { key: "target_cash_on_cash", label: "Cash-on-Cash", value: fmtPct(asNum(tr.target_cash_on_cash), 1) },
    { key: "hold_period_years", label: "Hold Period", value: fmtYears(asNum(ds.hold_period_years)) },
    { key: "preferred_return", label: "Pref Return", value: fmtPct(asNum(ds.preferred_return), 1) },
    { key: "ltv", label: "LTV", value: fmtPct(asNum(ds.ltv), 0) },
    { key: "total_project_cost", label: "Project Cost", value: fmtMoney(asNum(ds.total_project_cost)) },
    { key: "total_equity_required", label: "Equity Required", value: fmtMoney(asNum(ds.total_equity_required)) },
  ];

  const provenance = deal.metrics?._provenance;

  return (
    <div className="space-y-6">
      <QualityPanel dealId={deal.id} quality={deal.quality} documents={deal.documents ?? []} />

      {/* 2-column: snapshot + scores */}
      <div className="grid grid-cols-1 lg:grid-cols-[1.2fr_1fr] gap-6">
        <Card elevated className="p-6">
          <h3 className="text-base font-semibold tracking-tight mb-4">Snapshot</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-5">
            {snapshot.map((s) => (
              <div key={s.key}>
                <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                  {s.label}
                </div>
                <div className="text-lg font-semibold tabular-nums mt-1">{s.value}</div>
              </div>
            ))}
          </div>
        </Card>
        <ScoreBreakdown scores={deal.scores ?? {}} />
      </div>

      <ValidationFlagsPanel flags={deal.metrics?.validation_flags} />

      {/* Key sections that belong on the first page */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <MetricsSection
          title="Deal structure"
          description="Capital stack, pref, fees, waterfall."
          sectionKey="deal_structure"
          data={deal.metrics?.deal_structure}
          keysOrder={HERO_KEYS}
          provenance={provenance}
          dealId={deal.id}
        />
        <MetricsSection
          title="Returns target"
          description="IRR, multiple, cash-on-cash."
          sectionKey="target_returns"
          data={deal.metrics?.target_returns}
          provenance={provenance}
          dealId={deal.id}
        />
      </div>
    </div>
  );
}

function asNum(v: unknown): number | null {
  if (typeof v === "number" && !Number.isNaN(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v))) return Number(v);
  return null;
}

function fmtYears(n: number | null): string {
  if (n == null) return "—";
  return `${n} ${n === 1 ? "yr" : "yrs"}`;
}
