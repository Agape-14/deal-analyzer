"use client";

import { Card } from "@/components/ui/card";
import { ScoreBreakdown } from "@/components/deal-detail/score-breakdown";
import { ValidationFlagsPanel } from "@/components/deal-detail/validation-flags";
import { MetricsSection } from "@/components/deal-detail/metrics-section";
import { AuditTrail } from "@/components/deal-detail/audit-trail";
import { QualityPanel } from "@/components/deal-detail/quality-panel";
import { ReviewQueue } from "@/components/deal-detail/review-queue";
import { PipelineTimeline } from "@/components/deal-detail/pipeline-timeline";
import { SourceCitations } from "@/components/deal-detail/source-citations";
import { UploadCompleteness } from "@/components/deal-detail/upload-completeness";
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
  const tr = (deal.metrics?.target_returns ?? {}) as Record<string, unknown>;
  const ds = (deal.metrics?.deal_structure ?? {}) as Record<string, unknown>;
  const fp = (deal.metrics?.financial_projections ?? {}) as Record<string, unknown>;
  const pd = (deal.metrics?.project_details ?? {}) as Record<string, unknown>;
  const cc = (deal.metrics?.construction_costs ?? {}) as Record<string, unknown>;
  const uc = (deal.metrics?.underwriting_checks ?? {}) as Record<string, unknown>;
  const se = (deal.metrics?.sponsor_evaluation ?? {}) as Record<string, unknown>;

  const provenance = (deal.metrics?._provenance ?? {}) as ProvenanceMap;
  const canonical = deal.metrics?._canonical_returns;
  const primaryStrategy = String(canonical?.primary_strategy ?? "").toLowerCase();
  const isHoldStrategy = primaryStrategy === "hold" || primaryStrategy === "hold_with_sale_option";
  const headlineIrr =
    asNum(canonical?.target_irr) ??
    (isHoldStrategy ? null : pickTrustedNumber(tr, provenance, ["target_returns.target_irr", "target_returns.net_irr"]));
  const headlineCashOnCash =
    asNum(canonical?.cash_on_cash) ??
    pickTrustedNumber(tr, provenance, [
      "target_returns.target_cash_on_cash",
      "target_returns.distribution_yield",
      "target_returns.hold_scenario.cash_on_cash_return",
      "target_returns.hold_scenario.distribution_yield",
    ]);
  const headlineMultiple = pickTrustedNumber(tr, provenance, ["target_returns.target_equity_multiple", "target_returns.net_equity_multiple"]);
  const quality = deal.quality && deal.scores?.data_quality
    ? { ...deal.quality, data_quality: deal.scores.data_quality }
    : deal.quality ?? deal.scores?.data_quality;
  const gate = deal.scores?.data_quality ?? (hasConfidenceExplanations(deal.quality) ? deal.quality : undefined);

  return (
    <div className="space-y-6">
      <ExecutiveReview
        deal={deal}
        gate={gate}
        headlineIrr={headlineIrr}
        headlineCashOnCash={headlineCashOnCash}
        headlineMultiple={headlineMultiple}
      />
      <ReviewQueue deal={deal} />

      <div className="grid grid-cols-1 lg:grid-cols-[1.2fr_1fr] gap-6 items-stretch">
        <SnapshotCard
          tr={tr}
          ds={ds}
          fp={fp}
          pd={pd}
          cc={cc}
          uc={uc}
          se={se}
          headlineIrr={headlineIrr}
          headlineCashOnCash={headlineCashOnCash}
          headlineMultiple={headlineMultiple}
        />
        <ScoreBreakdown scores={deal.scores ?? {}} />
      </div>

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
    </div>
  );
}

function ExecutiveReview({
  deal,
  gate,
  headlineIrr,
  headlineCashOnCash,
  headlineMultiple,
}: {
  deal: DealDetail;
  gate?: DataQualityGate;
  headlineIrr: number | null;
  headlineCashOnCash: number | null;
  headlineMultiple: number | null;
}) {
  const metrics = deal.metrics ?? {};
  const tr = (metrics.target_returns ?? {}) as Record<string, unknown>;
  const ds = (metrics.deal_structure ?? {}) as Record<string, unknown>;
  const fp = (metrics.financial_projections ?? {}) as Record<string, unknown>;
  const canonical = metrics._canonical_returns;
  const readiness = readinessCopy(gate);
  const strategy = strategyText(canonical?.primary_strategy ?? tr.primary_strategy ?? ds.primary_strategy);
  const docs = deal.documents ?? [];
  const readableDocs = docs.filter((doc) => doc.has_text).length;
  const nextAction = gate?.next_actions?.[0] ?? readiness.action;
  const primaryReturnLabel = headlineIrr !== null ? "Target IRR" : "Cash-on-Cash";
  const primaryReturnValue = headlineIrr !== null ? headlineIrr : headlineCashOnCash;

  return (
    <div className="grid gap-4 xl:grid-cols-[1.25fr_0.75fr]">
      <Card elevated className="p-6">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-3xl">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Executive review</span>
              <span className={`rounded-full px-2.5 py-1 text-xs font-medium ring-1 ${readiness.className}`}>{readiness.label}</span>
            </div>
            <h2 className="mt-3 text-xl font-semibold tracking-tight">{readiness.headline}</h2>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{readiness.detail}</p>
          </div>
          <div className="rounded-lg border border-border/80 bg-muted/25 px-4 py-3 text-sm lg:w-72">
            <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Next best action</div>
            <div className="mt-1.5 font-medium leading-snug text-foreground">{nextAction}</div>
          </div>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-3">
          <SummaryPoint label="Base strategy" value={strategy} detail="Use this lens unless the documents clearly say another scenario is preferred." />
          <SummaryPoint label="Documents read" value={`${readableDocs}/${docs.length || 0}`} detail="Review documents again if a new upload is missing from this count." />
          <SummaryPoint label="Score trust" value={readiness.trust} detail="The review queue below is the only place users need to clear open items." />
        </div>
      </Card>

      <Card elevated className="p-6">
        <h3 className="text-base font-semibold tracking-tight">Key assumptions</h3>
        <div className="mt-4 grid grid-cols-2 gap-4">
          <Stat label={primaryReturnLabel} value={fmtPct(primaryReturnValue, 1)} />
          <Stat label="Multiple" value={fmtMultiple(headlineMultiple)} />
          <Stat label="Min Investment" value={fmtMoney(deal.minimum_investment)} />
          <Stat label="Project Cost" value={fmtMoney(asNum(ds.total_project_cost))} />
          <Stat label="Debt" value={fmtMoney(asNum(ds.debt_amount))} />
          <Stat label="NOI" value={fmtMoney(asNum(fp.stabilized_noi))} />
        </div>
      </Card>
    </div>
  );
}

function SnapshotCard({
  tr,
  ds,
  fp,
  pd,
  cc,
  uc,
  se,
  headlineIrr,
  headlineCashOnCash,
  headlineMultiple,
}: {
  tr: Record<string, unknown>;
  ds: Record<string, unknown>;
  fp: Record<string, unknown>;
  pd: Record<string, unknown>;
  cc: Record<string, unknown>;
  uc: Record<string, unknown>;
  se: Record<string, unknown>;
  headlineIrr: number | null;
  headlineCashOnCash: number | null;
  headlineMultiple: number | null;
}) {
  return (
    <Card elevated className="p-6 flex flex-col">
      <h3 className="text-base font-semibold tracking-tight mb-1">Deal snapshot</h3>
      <p className="mb-5 text-sm text-muted-foreground">The main numbers used for quick underwriting. Open technical details for every extracted field.</p>

      <div className="grid grid-cols-2 gap-x-6 gap-y-4 md:grid-cols-4">
        <Stat label="Target IRR" value={fmtPct(headlineIrr, 1)} />
        <Stat label="Equity Multiple" value={fmtMultiple(headlineMultiple)} />
        <Stat label="Cash-on-Cash" value={fmtPct(headlineCashOnCash, 1)} />
        <Stat label="Hold Period" value={fmtYears(asNum(ds.hold_period_years))} />
        <Stat label="Pref Return" value={fmtPct(asNum(ds.preferred_return), 1)} />
        <Stat label="LTV" value={fmtPct(asNum(ds.ltv), 0)} />
        <Stat label="Project Cost" value={fmtMoney(asNum(ds.total_project_cost))} />
        <Stat label="Equity Required" value={fmtMoney(asNum(ds.total_equity_required))} />
      </div>

      <div className="border-t border-border/60 my-4" />

      <div className="grid grid-cols-2 gap-x-6 gap-y-4 md:grid-cols-4">
        <Stat label="Units" value={fmtInt(asNum(pd.unit_count))} />
        <Stat label="Cost / Unit" value={fmtMoney(asNum(cc.total_project_cost_per_unit ?? pd.price_per_unit))} />
        <Stat label="Hard Cost / Unit" value={fmtMoney(asNum(cc.hard_costs_per_unit))} />
        <Stat label="Land Cost / Unit" value={fmtMoney(asNum(cc.land_cost_per_unit))} />
        <Stat label="Avg Rent" value={fmtMoney(asNum(fp.avg_rent_per_unit))} sub="/mo" />
        <Stat label="Occupancy" value={fmtPct(asNum(fp.occupancy_assumption), 0)} />
        <Stat label="DSCR" value={fmtX(asNum(uc.dscr))} />
        <Stat label="Yield on Cost" value={fmtPct(asNum(uc.yield_on_cost), 1)} />
      </div>

      <div className="border-t border-border/60 my-4" />

      <div className="grid grid-cols-2 gap-x-6 gap-y-4 md:grid-cols-4">
        <Stat label="GP Co-Invest" value={fmtPct(asNum(ds.gp_equity_coinvest_pct), 0)} />
        <Stat label="GP Cash at Risk" value={fmtMoney(asNum(ds.gp_cash_at_risk))} />
        <Stat label="Interest Rate" value={fmtPct(asNum(ds.interest_rate), 1)} />
        <Stat label="Sponsor" value={strVal(se.sponsor_name)} small />
      </div>
    </Card>
  );
}

function SummaryPoint({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="rounded-lg border border-border/70 bg-muted/20 px-3 py-3">
      <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">{label}</div>
      <div className="mt-1 text-sm font-semibold text-foreground">{value}</div>
      <div className="mt-1 text-xs leading-relaxed text-muted-foreground">{detail}</div>
    </div>
  );
}

function readinessCopy(gate?: DataQualityGate) {
  const stage = String(gate?.stage ?? "").toLowerCase();
  const confidence = typeof gate?.confidence_score === "number" ? Math.round(gate.confidence_score) : null;
  const critical = gate?.critical_summary;
  const openCritical =
    (critical?.missing ?? 0) +
    (critical?.conflicted ?? 0) +
    (critical?.bad ?? 0) +
    (critical?.review_only ?? 0);
  const mathFailures = gate?.math_summary?.fail ?? gate?.math_summary?.blocking?.length ?? 0;
  const openItems = openCritical + mathFailures;

  if (stage === "verified" && openItems === 0) {
    return {
      label: "Ready to use",
      headline: "The score can be used for comparison.",
      detail: "The documents have been read, key values were source-checked, and no blocking review items are open.",
      action: "Compare the deal against alternatives or export the underwriting summary.",
      trust: confidence === null ? "Verified" : `${confidence}% confidence`,
      className: "bg-success/15 text-success ring-success/30",
    };
  }

  if (stage === "blocked") {
    return {
      label: "Blocked",
      headline: "The score should not be trusted yet.",
      detail: "Required information is missing, contradicted, or could not be tied back to the uploaded documents.",
      action: "Clear the review queue below before using the score.",
      trust: confidence === null ? "Blocked" : `${confidence}% confidence`,
      className: "bg-destructive/15 text-destructive ring-destructive/30",
    };
  }

  if (stage.includes("incomplete")) {
    return {
      label: "Document review incomplete",
      headline: "The score may be based on partial document reading.",
      detail: "Review documents again after API limits clear, then confirm any remaining items in the review queue.",
      action: "Run Review documents again before relying on the score.",
      trust: confidence === null ? "Incomplete" : `${confidence}% confidence`,
      className: "bg-warning/15 text-warning ring-warning/30",
    };
  }

  return {
    label: "Needs review",
    headline: openItems > 0 ? `${openItems} item${openItems === 1 ? "" : "s"} need review before the score is trusted.` : "Confirm the review queue before relying on the score.",
    detail: "The app has extracted useful information, but a few assumptions still need a human confirmation or correction.",
    action: "Start with the first item in the review queue.",
    trust: confidence === null ? "Needs review" : `${confidence}% confidence`,
    className: "bg-warning/15 text-warning ring-warning/30",
  };
}

function strategyText(value: unknown): string {
  const text = typeof value === "string" ? value.trim() : "";
  if (!text) return "Not confirmed yet";
  return text.replace(/_/g, " ").replace(/\b\w/g, (match) => match.toUpperCase());
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

function pickTrustedNumber(block: Record<string, unknown>, provenance: ProvenanceMap, paths: string[]): number | null {
  const candidates = paths
    .map((path) => ({ path, value: asNum(block[path.split(".").at(-1) ?? path]), provenance: provenance[path] }))
    .filter((candidate) => candidate.value !== null);

  if (candidates.length === 0) return null;
  const clean = candidates.filter((candidate) => !isBadSource(candidate.provenance));
  const reviewed = clean.find((candidate) => candidate.provenance?.locked || ["manual", "confirmed", "calculated"].includes(String(candidate.provenance?.status ?? "")));
  return (reviewed ?? clean[0] ?? candidates[0]).value;
}

function isBadSource(provenance?: FieldProvenance): boolean {
  if (!provenance) return false;
  const status = String(provenance.status ?? "").toLowerCase();
  const conflictCount = Array.isArray(provenance.conflict) ? provenance.conflict.length : 0;
  return conflictCount > 1 || ["wrong", "missing", "unverifiable", "stale"].includes(status);
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
