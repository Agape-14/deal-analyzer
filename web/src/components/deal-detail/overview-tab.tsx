"use client";

import * as React from "react";
import type { ReactNode } from "react";
import { Card } from "@/components/ui/card";
import { ScoreBreakdown } from "@/components/deal-detail/score-breakdown";
import { ValidationFlagsPanel } from "@/components/deal-detail/validation-flags";
import { MetricsSection } from "@/components/deal-detail/metrics-section";
import { AuditTrail } from "@/components/deal-detail/audit-trail";
import { QualityPanel } from "@/components/deal-detail/quality-panel";
import { ReviewQueue } from "@/components/deal-detail/review-queue";
import { PipelineTimeline } from "@/components/deal-detail/pipeline-timeline";
import { SourceDetailsDrawer } from "@/components/deal-detail/source-details-drawer";
import { SourceCitations } from "@/components/deal-detail/source-citations";
import { UploadCompleteness } from "@/components/deal-detail/upload-completeness";
import { useCurrentUser } from "@/lib/auth-client";
import { getHeadlineReturnMetrics } from "@/lib/return-metrics";
import type { DataQualityGate, DealDetail, FieldProvenance } from "@/lib/types";
import { fmtMoney, fmtMultiple, fmtPct } from "@/lib/utils";

const HERO_KEYS = [
  "target_irr",
  "target_equity_multiple",
  "target_cash_on_cash",
  "hold_period_years",
  "preferred_return",
  "ltv",
] as const;

type ProvenanceMap = Record<string, FieldProvenance>;

export function OverviewTab({ deal }: { deal: DealDetail }) {
  const { isAnalyst, loading } = useCurrentUser();
  const showAnalyst = !loading && isAnalyst;
  const ds = (deal.metrics?.deal_structure ?? {}) as Record<string, unknown>;
  const fp = (deal.metrics?.financial_projections ?? {}) as Record<string, unknown>;
  const pd = (deal.metrics?.project_details ?? {}) as Record<string, unknown>;
  const cc = (deal.metrics?.construction_costs ?? {}) as Record<string, unknown>;
  const uc = (deal.metrics?.underwriting_checks ?? {}) as Record<string, unknown>;
  const se = (deal.metrics?.sponsor_evaluation ?? {}) as Record<string, unknown>;

  const provenance = (deal.metrics?._provenance ?? {}) as ProvenanceMap;
  const { headlineIrr, headlineCashOnCash, headlineMultiple } = getHeadlineReturnMetrics(deal);
  const canonical = deal.metrics?._canonical_returns;
  const sourcePaths = {
    headlineIrr: canonical?.target_irr_path ?? "target_returns.target_irr",
    headlineCashOnCash: canonical?.cash_on_cash_path ?? "target_returns.target_cash_on_cash",
    headlineMultiple: canonical?.target_equity_multiple_path ?? "target_returns.target_equity_multiple",
  };
  const quality = deal.quality && deal.scores?.data_quality
    ? { ...deal.quality, data_quality: deal.scores.data_quality }
    : deal.quality ?? deal.scores?.data_quality;
  const gate = deal.scores?.data_quality ?? (hasConfidenceExplanations(deal.quality) ? deal.quality : undefined);
  return (
    <div className="space-y-6">
      {showAnalyst ? (
        <section id="admin-review-center" aria-label="Admin review queue">
          <ReviewQueue deal={deal} />
        </section>
      ) : null}

      <div id="deal-summary" className="scroll-mt-28 grid grid-cols-1 gap-6 lg:grid-cols-[1.2fr_1fr] lg:items-stretch">
        <SnapshotCard
          ds={ds}
          fp={fp}
          pd={pd}
          cc={cc}
          uc={uc}
          se={se}
          provenance={provenance}
          sourcePaths={sourcePaths}
          showAdminAction={showAnalyst}
          headlineIrr={headlineIrr}
          headlineCashOnCash={headlineCashOnCash}
          headlineMultiple={headlineMultiple}
        />
        <ScoreBreakdown scores={deal.scores ?? {}} viewerMode={!showAnalyst} />
      </div>

      {showAnalyst ? (
        <>
          <details className="group">
            <summary className="cursor-pointer list-none rounded-xl border border-border/80 bg-card/70 p-4 text-sm font-semibold tracking-tight text-foreground shadow-sm marker:hidden">
              <span className="flex flex-wrap items-center justify-between gap-3">
                <span>Evidence and sources</span>
                <span className="text-xs font-normal text-muted-foreground group-open:hidden">Show document coverage and citations</span>
                <span className="hidden text-xs font-normal text-muted-foreground group-open:inline">Hide evidence</span>
              </span>
            </summary>
            <div className="mt-4 space-y-6">
              <UploadCompleteness deal={deal} />
              <div id="source-citations">
                <SourceCitations deal={deal} />
              </div>
            </div>
          </details>

          <details id="technical-details" className="group">
            <summary className="cursor-pointer list-none rounded-xl border border-border/80 bg-card/70 p-4 text-sm font-semibold tracking-tight text-foreground shadow-sm marker:hidden">
              <span className="flex flex-wrap items-center justify-between gap-3">
                <span>Technical audit details</span>
                <span className="text-xs font-normal text-muted-foreground group-open:hidden">Show extraction counters, math status, flags, and field history</span>
                <span className="hidden text-xs font-normal text-muted-foreground group-open:inline">Hide technical details</span>
              </span>
            </summary>
            <div className="mt-4 space-y-6">
              <QualityPanel dealId={deal.id} quality={quality} documents={deal.documents ?? []} />
              <PipelineTimeline deal={deal} />
              <ConfidenceExplainer gate={gate} />
              <ValidationFlagsPanel flags={deal.metrics?.validation_flags} />
              <AuditTrail deal={deal} />

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
          </details>
        </>
      ) : (
        <ViewerSourceStatus deal={deal} gate={gate} />
      )}
    </div>
  );
}

function ViewerSourceStatus({ deal, gate }: { deal: DealDetail; gate?: DataQualityGate }) {
  const docs = deal.documents ?? [];
  const readableDocs = docs.filter((doc) => doc.has_text).length;
  const confidence = typeof gate?.confidence_score === "number" ? Math.round(gate.confidence_score) : null;
  const stage = String(gate?.stage ?? "").toLowerCase();
  const isVerified = stage === "verified";
  const sourceLabel = isVerified ? "Source check complete" : stage.includes("incomplete") ? "Source check in progress" : "Source check available";
  const confidenceText = confidence === null ? "Confidence pending" : `${confidence}% source confidence`;

  return (
    <Card className="border-border/80 bg-card/80 p-5 shadow-sm">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="text-[10px] font-extrabold uppercase tracking-[0.16em] text-primary">Source status</div>
          <h3 className="mt-1 text-base font-bold text-foreground">{sourceLabel}</h3>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted-foreground">
            {readableDocs}/{docs.length || 0} uploaded documents have readable text. {confidenceText}. Admin users can open the full audit trail and citations.
          </p>
        </div>
        <div className="rounded-lg border border-border/80 bg-background px-4 py-3 text-sm font-semibold text-foreground">
          {isVerified ? "Ready for team review" : "Working summary"}
        </div>
      </div>
    </Card>
  );
}

function SnapshotCard({
  ds,
  fp,
  pd,
  cc,
  uc,
  se,
  provenance,
  sourcePaths,
  showAdminAction,
  headlineIrr,
  headlineCashOnCash,
  headlineMultiple,
}: {
  ds: Record<string, unknown>;
  fp: Record<string, unknown>;
  pd: Record<string, unknown>;
  cc: Record<string, unknown>;
  uc: Record<string, unknown>;
  se: Record<string, unknown>;
  provenance: ProvenanceMap;
  sourcePaths: {
    headlineIrr?: string | null;
    headlineCashOnCash?: string | null;
    headlineMultiple?: string | null;
  };
  showAdminAction: boolean;
  headlineIrr: number | null;
  headlineCashOnCash: number | null;
  headlineMultiple: number | null;
}) {
  const sourceFor = (path?: string | null) => (path ? provenance[path] : undefined);

  return (
    <Card className="overflow-hidden border-border/80 bg-card p-0 shadow-sm">
      <div className="border-b border-border/80 bg-muted/25 px-6 py-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="text-[10px] font-extrabold uppercase tracking-[0.16em] text-primary">Underwriting Snapshot</div>
            <h3 className="mt-1 text-xl font-bold text-foreground">Deal snapshot</h3>
            <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted-foreground">
              The high-signal assumptions used for quick underwriting, grouped like an investment committee summary.
            </p>
          </div>
          <div className="w-fit rounded-full border border-border/80 bg-background px-3 py-1 text-xs font-semibold text-muted-foreground">
            Quick read
          </div>
        </div>
      </div>

      <div className="space-y-4 p-5 md:p-6">
        <SnapshotGroup title="Return Profile" description="Headline return targets and sponsor economics." tone="primary">
          <Stat label="Target IRR" value={fmtPct(headlineIrr, 1)} path={sourcePaths.headlineIrr} provenance={sourceFor(sourcePaths.headlineIrr)} showAdminAction={showAdminAction} emphasis />
          <Stat label="Equity Multiple" value={fmtMultiple(headlineMultiple)} path={sourcePaths.headlineMultiple} provenance={sourceFor(sourcePaths.headlineMultiple)} showAdminAction={showAdminAction} emphasis />
          <Stat label="Cash-on-Cash" value={fmtPct(headlineCashOnCash, 1)} path={sourcePaths.headlineCashOnCash} provenance={sourceFor(sourcePaths.headlineCashOnCash)} showAdminAction={showAdminAction} emphasis />
          <Stat label="Hold Period" value={fmtYears(asNum(ds.hold_period_years))} path="deal_structure.hold_period_years" provenance={provenance["deal_structure.hold_period_years"]} showAdminAction={showAdminAction} />
          <Stat label="Pref Return" value={fmtPct(asNum(ds.preferred_return), 1)} path="deal_structure.preferred_return" provenance={provenance["deal_structure.preferred_return"]} showAdminAction={showAdminAction} />
          <Stat label="LTV" value={fmtPct(asNum(ds.ltv), 0)} path="deal_structure.ltv" provenance={provenance["deal_structure.ltv"]} showAdminAction={showAdminAction} />
          <Stat label="Project Cost" value={fmtMoney(asNum(ds.total_project_cost))} path="deal_structure.total_project_cost" provenance={provenance["deal_structure.total_project_cost"]} showAdminAction={showAdminAction} />
          <Stat label="Equity Required" value={fmtMoney(asNum(ds.total_equity_required))} path="deal_structure.total_equity_required" provenance={provenance["deal_structure.total_equity_required"]} showAdminAction={showAdminAction} />
        </SnapshotGroup>

        <SnapshotGroup title="Property Metrics" description="Scale, rent, occupancy, and cost-per-unit checks." tone="success">
          <Stat label="Units" value={fmtInt(asNum(pd.unit_count))} path="project_details.unit_count" provenance={provenance["project_details.unit_count"]} showAdminAction={showAdminAction} />
          <Stat label="Cost / Unit" value={fmtMoney(asNum(cc.total_project_cost_per_unit ?? pd.price_per_unit))} path="construction_costs.total_project_cost_per_unit" provenance={provenance["construction_costs.total_project_cost_per_unit"] ?? provenance["project_details.price_per_unit"]} showAdminAction={showAdminAction} />
          <Stat label="Hard Cost / Unit" value={fmtMoney(asNum(cc.hard_costs_per_unit))} path="construction_costs.hard_costs_per_unit" provenance={provenance["construction_costs.hard_costs_per_unit"]} showAdminAction={showAdminAction} />
          <Stat label="Land Cost / Unit" value={fmtMoney(asNum(cc.land_cost_per_unit))} path="construction_costs.land_cost_per_unit" provenance={provenance["construction_costs.land_cost_per_unit"]} showAdminAction={showAdminAction} />
          <Stat label="Avg Rent" value={fmtMoney(asNum(fp.avg_rent_per_unit))} sub="/mo" path="financial_projections.avg_rent_per_unit" provenance={provenance["financial_projections.avg_rent_per_unit"]} showAdminAction={showAdminAction} />
          <Stat label="Occupancy" value={fmtPct(asNum(fp.occupancy_assumption), 0)} path="financial_projections.occupancy_assumption" provenance={provenance["financial_projections.occupancy_assumption"]} showAdminAction={showAdminAction} />
          <Stat label="DSCR" value={fmtX(asNum(uc.dscr))} path="underwriting_checks.dscr" provenance={provenance["underwriting_checks.dscr"]} showAdminAction={showAdminAction} />
          <Stat label="Yield on Cost" value={fmtPct(asNum(uc.yield_on_cost), 1)} path="underwriting_checks.yield_on_cost" provenance={provenance["underwriting_checks.yield_on_cost"]} showAdminAction={showAdminAction} />
        </SnapshotGroup>

        <SnapshotGroup title="Sponsor and Debt" description="Alignment and financing assumptions to confirm before relying on the score." tone="warning">
          <Stat label="GP Co-Invest" value={fmtPct(asNum(ds.gp_equity_coinvest_pct), 0)} path="deal_structure.gp_equity_coinvest_pct" provenance={provenance["deal_structure.gp_equity_coinvest_pct"]} showAdminAction={showAdminAction} />
          <Stat label="GP Cash at Risk" value={fmtMoney(asNum(ds.gp_cash_at_risk))} path="deal_structure.gp_cash_at_risk" provenance={provenance["deal_structure.gp_cash_at_risk"]} showAdminAction={showAdminAction} />
          <Stat label="Interest Rate" value={fmtPct(asNum(ds.interest_rate), 1)} path="deal_structure.interest_rate" provenance={provenance["deal_structure.interest_rate"]} showAdminAction={showAdminAction} />
          <Stat label="Sponsor" value={strVal(se.sponsor_name)} path="sponsor_evaluation.sponsor_name" provenance={provenance["sponsor_evaluation.sponsor_name"]} showAdminAction={showAdminAction} small />
        </SnapshotGroup>
      </div>
    </Card>
  );
}

function SnapshotGroup({
  title,
  description,
  tone,
  children,
}: {
  title: string;
  description: string;
  tone: "primary" | "success" | "warning";
  children: ReactNode;
}) {
  const toneClass = tone === "success" ? "bg-success" : tone === "warning" ? "bg-warning" : "bg-primary";

  return (
    <section className="overflow-hidden rounded-xl border border-border/80 bg-background">
      <div className="border-b border-border/70 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className={`h-2.5 w-2.5 rounded-full ${toneClass}`} />
          <h4 className="text-xs font-extrabold uppercase tracking-[0.14em] text-foreground">{title}</h4>
        </div>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{description}</p>
      </div>
      <div className="grid grid-cols-2 divide-x divide-y divide-border/70 md:grid-cols-4">
        {children}
      </div>
    </section>
  );
}

function ConfidenceExplainer({ gate }: { gate?: DataQualityGate }) {
  const explanations = gate?.confidence_explanations ?? [];
  if (!gate || explanations.length === 0) return null;
  const primary = explanations[0];
  if (gate.stage === "verified" && primary.severity === "success") return null;
  return (
    <Card className="p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="text-sm font-semibold tracking-tight">Why confidence is {Math.round(gate.confidence_score)}%</div>
          <div className="mt-1 text-sm text-muted-foreground">{primary.detail}</div>
        </div>
        <div className="rounded-lg border border-border/80 bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          {primary.action ?? gate.next_actions?.[0] ?? "Resolve the review queue items above."}
        </div>
      </div>
      {explanations.length > 1 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {explanations.slice(1, 4).map((item, index) => (
            <span key={`${item.label}-${index}`} className="rounded-full border border-border/80 bg-background px-2.5 py-1 text-xs text-muted-foreground">
              {item.label}
            </span>
          ))}
        </div>
      )}
    </Card>
  );
}

function hasConfidenceExplanations(value: unknown): value is DataQualityGate {
  return Boolean(value && typeof value === "object" && "confidence_explanations" in value);
}

function Stat({
  label,
  value,
  sub,
  path,
  provenance,
  showAdminAction,
  small,
  emphasis,
}: {
  label: string;
  value: string;
  sub?: string;
  path?: string | null;
  provenance?: FieldProvenance;
  showAdminAction?: boolean;
  small?: boolean;
  emphasis?: boolean;
}) {
  const [open, setOpen] = React.useState(false);
  const tileClass = emphasis ? "bg-primary/5" : "bg-card";
  const sourceAvailable = Boolean(path || provenance);
  const valueClass = `mt-1.5 font-extrabold tabular-nums leading-none ${emphasis ? "text-primary" : "text-foreground"} ${small ? "truncate text-sm leading-tight" : "text-[1.25rem]"}`;

  return (
    <div className={`min-w-0 px-4 py-3.5 ${tileClass}`}>
      <div className="text-[11px] font-extrabold uppercase tracking-[0.1em] text-foreground/70">{label}</div>
      {sourceAvailable ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          data-figure
          className={`${valueClass} max-w-full text-left transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`}
          aria-label={`Open source for ${label}`}
        >
          {value}{sub && <span className="text-xs text-muted-foreground font-normal">{sub}</span>}
        </button>
      ) : (
        <div data-figure className={valueClass}>
          {value}{sub && <span className="text-xs text-muted-foreground font-normal">{sub}</span>}
        </div>
      )}
      {open ? (
        <SourceDetailsDrawer
          open={open}
          onOpenChange={setOpen}
          label={label}
          value={`${value}${sub ?? ""}`}
          path={path}
          provenance={provenance}
          showAdminAction={Boolean(showAdminAction)}
        />
      ) : null}
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
  return "-";
}

function fmtYears(n: number | null): string {
  if (n == null) return "-";
  return `${n} ${n === 1 ? "yr" : "yrs"}`;
}

function fmtInt(n: number | null): string {
  if (n == null) return "-";
  return Math.round(n).toLocaleString();
}

function fmtX(n: number | null): string {
  if (n == null) return "-";
  return `${n.toFixed(2)}x`;
}
