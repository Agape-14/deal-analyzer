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
  const fp = (deal.metrics?.financial_projections ?? {}) as Record<string, unknown>;
  const pd = (deal.metrics?.project_details ?? {}) as Record<string, unknown>;
  const cc = (deal.metrics?.construction_costs ?? {}) as Record<string, unknown>;
  const uc = (deal.metrics?.underwriting_checks ?? {}) as Record<string, unknown>;
  const se = (deal.metrics?.sponsor_evaluation ?? {}) as Record<string, unknown>;

  const provenance = deal.metrics?._provenance;

  return (
    <div className="space-y-6">
      <QualityPanel dealId={deal.id} quality={deal.quality} documents={deal.documents ?? []} />

      {/* 2-column: snapshot + scores */}
      <div className="grid grid-cols-1 lg:grid-cols-[1.2fr_1fr] gap-6 items-stretch">
        <Card elevated className="p-6 flex flex-col">
          <h3 className="text-base font-semibold tracking-tight mb-4">Snapshot</h3>

          {/* Returns & Structure */}
          <div className="grid grid-cols-4 gap-x-6 gap-y-4">
            <Stat label="Target IRR" value={fmtPct(asNum(tr.target_irr), 1)} />
            <Stat label="Equity Multiple" value={fmtMultiple(asNum(tr.target_equity_multiple))} />
            <Stat label="Cash-on-Cash" value={fmtPct(asNum(tr.target_cash_on_cash), 1)} />
            <Stat label="Hold Period" value={fmtYears(asNum(ds.hold_period_years))} />
            <Stat label="Pref Return" value={fmtPct(asNum(ds.preferred_return), 1)} />
            <Stat label="LTV" value={fmtPct(asNum(ds.ltv), 0)} />
            <Stat label="Project Cost" value={fmtMoney(asNum(ds.total_project_cost))} />
            <Stat label="Equity Required" value={fmtMoney(asNum(ds.total_equity_required))} />
          </div>

          {/* Divider */}
          <div className="border-t border-border/60 my-4" />

          {/* Project & Construction */}
          <div className="grid grid-cols-4 gap-x-6 gap-y-4">
            <Stat label="Units" value={fmtInt(asNum(pd.unit_count))} />
            <Stat label="Cost / Unit" value={fmtMoney(asNum(cc.total_project_cost_per_unit ?? pd.price_per_unit))} />
            <Stat label="Hard Cost / Unit" value={fmtMoney(asNum(cc.hard_costs_per_unit))} />
            <Stat label="Land Cost / Unit" value={fmtMoney(asNum(cc.land_cost_per_unit))} />
            <Stat label="Avg Rent" value={fmtMoney(asNum(fp.avg_rent_per_unit))} sub="/mo" />
            <Stat label="Occupancy" value={fmtPct(asNum(fp.occupancy_assumption), 0)} />
            <Stat label="DSCR" value={fmtX(asNum(uc.dscr))} />
            <Stat label="Yield on Cost" value={fmtPct(asNum(uc.yield_on_cost), 1)} />
          </div>

          {/* Divider */}
          <div className="border-t border-border/60 my-4" />

          {/* Sponsor */}
          <div className="grid grid-cols-4 gap-x-6 gap-y-4">
            <Stat label="GP Co-Invest" value={fmtPct(asNum(ds.gp_equity_coinvest_pct), 0)} />
            <Stat label="GP Cash at Risk" value={fmtMoney(asNum(ds.gp_cash_at_risk))} />
            <Stat label="Interest Rate" value={fmtPct(asNum(ds.interest_rate), 1)} />
            <Stat label="Sponsor" value={strVal(se.sponsor_name)} small />
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

function Stat({ label, value, sub, small }: { label: string; value: string; sub?: string; small?: boolean }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">{label}</div>
      <div className={`font-semibold tabular-nums mt-1 ${small ? "text-sm truncate" : "text-lg"}`}>
        {value}{sub && <span className="text-xs text-muted-foreground font-normal">{sub}</span>}
      </div>
    </div>
  );
}

function asNum(v: unknown): number | null {
  if (typeof v === "number" && !Number.isNaN(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v))) return Number(v);
  return null;
}

function strVal(v: unknown): string {
  if (typeof v === "string" && v.trim()) return v;
  return "—";
}

function fmtYears(n: number | null): string {
  if (n == null) return "—";
  return `${n} ${n === 1 ? "yr" : "yrs"}`;
}

function fmtInt(n: number | null): string {
  if (n == null) return "—";
  return Math.round(n).toLocaleString();
}

function fmtX(n: number | null): string {
  if (n == null) return "—";
  return `${n.toFixed(2)}x`;
}
