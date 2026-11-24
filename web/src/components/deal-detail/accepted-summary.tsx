"use client";

import Link from "next/link";
import { Card } from "@/components/ui/card";
import type { AnalysisFact, DealDetail } from "@/lib/types";
import { fmtMoney, fmtPct, fmtMultiple } from "@/lib/utils";
import { operatingFactContext } from "@/lib/fact-context";
import { sourceFindingsNeedReview } from "@/lib/review-attention";
import { EvidenceViewer } from "./evidence-viewer";
import { ReturnContextPanel } from "./return-context-panel";
import { ReturnCrosscheckPanel } from "./return-crosscheck";
import { ReturnSchedulePanel } from "./return-schedule-panel";
import { FinancingMeasuresPanel } from "./financing-measures-panel";
import { ScoreBreakdown } from "./score-breakdown";
import { ReadinessChecks, ReviewCoveragePanel } from "./review-coverage";

const detailSections = [
  { prefix: "deal_structure.", title: "Investment and financing terms" },
  { prefix: "project_details.", title: "Project details" },
  { prefix: "construction_costs.", title: "Construction costs" },
  { prefix: "financial_projections.", title: "Financial projections" },
  { prefix: "underwriting_checks.", title: "Underwriting" },
  { prefix: "market_location.", title: "Market and location" },
  { prefix: "sponsor_evaluation.", title: "Sponsor" },
] as const;

export function factValue(fact?: AnalysisFact, reported = false): string {
  if (!fact || fact.value == null || (!reported && !["checked", "calculated", "manual"].includes(fact.state))) return "Awaiting evidence";
  const v = fact.value;
  if (Array.isArray(v)) return v.map(t => `${t.threshold}% hurdle: ${t.lp_split}% LP / ${t.gp_split}% GP`).join("; ");
  if (typeof v === "string") return v;
  if (fact.identity.unit === "currency") return fmtMoney(v);
  if (fact.identity.unit === "percent") return fmtPct(v);
  if (fact.identity.unit === "multiple") return fmtMultiple(v);
  if (["years", "months"].includes(fact.identity.unit)) return `${v} ${fact.identity.unit}`;
  return v.toLocaleString();
}

export function FactEvidence({ fact }: { fact?: AnalysisFact }) {
  if (!fact) return null;
  return <details className="mt-2 text-xs text-muted-foreground">
    <summary className="cursor-pointer">Evidence · {fact.state === "manual" ? "Analyst resolved" : fact.state}</summary>
    <div className="mt-2 space-y-2 leading-relaxed">
      {fact.reason && <p>{fact.reason}</p>}
      {[fact.identity.basis, fact.identity.period, fact.identity.debt_phase, fact.identity.currency].some(value => value && value !== "unspecified") && <p>{[fact.identity.basis, fact.identity.period, fact.identity.debt_phase, fact.identity.currency].filter(value => value && value !== "unspecified").join(" · ")}</p>}
      {fact.formula && <p>Calculated: {fact.formula}</p>}
      {fact.dependencies.length > 0 && <p>Inputs: {fact.dependencies.map(p => p.split(".").pop()?.replaceAll("_", " ")).join(", ")}</p>}
      {fact.evidence.map((e, i) => <div key={`${e.document_id}-${i}`}>
        <EvidenceViewer source={e} />
        {e.excerpt && <p className="mt-1 whitespace-pre-wrap">{e.excerpt}</p>}
      </div>)}
      {fact.alternatives.length > 0 && <p>Source alternatives: {fact.alternatives.map(v => typeof v === "object" ? JSON.stringify(v) : String(v)).join("; ")}</p>}
    </div>
  </details>;
}

export function AcceptedSummary({ deal }: { deal: DealDetail }) {
  const analysis = deal.analysis;
  if (!analysis) return <Card className="p-6">Analysis is unavailable. Reload after document review completes.</Card>;
  const facts = analysis.facts;
  const financingSourcePaths = new Set(analysis.financing?.measures.map(measure => measure.source_path));
  const paths = ["deal_structure.total_project_cost", "deal_structure.total_equity_required", "deal_structure.debt_amount", "deal_structure.minimum_investment", "deal_structure.hold_period_years", "project_details.unit_count", "financial_projections.stabilized_noi", "underwriting_checks.dscr"];
  const acceptedPaths = paths.filter(path => facts[path] && ["checked", "calculated", "manual"].includes(facts[path].state));
  const pendingPaths = paths.filter(path => !acceptedPaths.includes(path));
  const debt = facts["deal_structure.debt_amount"]?.value;
  const acceptedDebtAmount = acceptedPaths.includes("deal_structure.debt_amount") && typeof debt === "number" ? debt : null;
  const intake = (deal.metrics as unknown as { _intake?: { name_origin?: string; auto_fields?: Record<string, { sources: Array<{ document_id: number; document_name: string; page?: number }> }>; identity_conflicts?: string[] } })._intake;
  return <div id="reviewed-facts" className="space-y-6 scroll-mt-20">
    <Card className="p-5 md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div><h2 className="text-lg font-semibold">One reviewed view of the deal</h2>
          <p className="mt-1 text-sm text-muted-foreground">{analysis.primary_strategy === "unknown" ? "Strategy needs clarification" : `Primary strategy: ${analysis.primary_strategy.replaceAll("_", " ")}`}{analysis.investor_class !== "unspecified" ? ` · ${analysis.investor_class}` : ""}</p>
        </div>
        <Link href={`/deals/${deal.id}?tab=questions`} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground">
          {analysis.questions.length || analysis.readiness?.attention_count || sourceFindingsNeedReview(analysis.findings)
            ? "Review exceptions" : analysis.findings?.length ? "Source findings" : "No material questions"}
        </Link>
      </div>
      {analysis.readiness && <div className="mt-4 border-t border-border/70 pt-4"><ReadinessChecks analysis={analysis} dealId={deal.id} /></div>}
      {analysis.review_coverage && <ReviewCoveragePanel coverage={analysis.review_coverage} dealId={deal.id} />}
      <details className="mt-3 text-xs text-muted-foreground"><summary className="cursor-pointer">Accepted facts · {analysis.coverage.accepted}/{analysis.coverage.total}</summary>
      <div className="mt-4 h-1.5 rounded-full bg-muted overflow-hidden" role="progressbar" aria-label="Accepted evidence coverage" aria-valuenow={analysis.coverage.accepted} aria-valuemin={0} aria-valuemax={analysis.coverage.total || 1}><div className="h-full bg-primary rounded-full" style={{ width: `${analysis.coverage.total ? analysis.coverage.accepted / analysis.coverage.total * 100 : 0}%` }} /></div>
      <p className="mt-3 text-sm text-muted-foreground">{analysis.coverage.accepted} of {analysis.coverage.total} recognized facts accepted · {analysis.coverage.checked} source checked · {analysis.coverage.calculated} calculated · {analysis.coverage.manual} analyst resolved.</p>
      <p className="mt-1 text-xs text-muted-foreground">Evidence coverage describes support for the numbers, not investment quality.</p>
      <p className="mt-2 text-xs text-muted-foreground">{analysis.version ? `Analysis revision ${analysis.version}` : "Preview of existing data"}{analysis.created_at ? ` · ${analysis.created_at.replace("T", " ").slice(0, 16)} UTC` : ""}. Missing or disputed facts remain withheld.</p>
      </details>
      {intake && <details className="mt-3 text-xs text-muted-foreground"><summary className="cursor-pointer">Deal details from your documents</summary><div className="mt-2 space-y-2">{intake.name_origin === "filename" && !intake.auto_fields?.project_name && <p>The deal title comes from the first filename. You can rename it in Analysis.</p>}{Object.entries(intake.auto_fields ?? {}).map(([key, meta]) => <p key={key}>{key.replaceAll("_", " ")}: {meta.sources.map((source, index) => <a key={index} className="underline mr-2" href={`/api/deals/documents/${source.document_id}/file${source.page ? `#page=${source.page}` : ""}`} target="_blank" rel="noreferrer">{source.document_name}{source.page ? ` · page ${source.page}` : ""}</a>)}</p>)}{!!intake.identity_conflicts?.length && <p className="text-warning">Conflicting document labels: {intake.identity_conflicts.map(key => key.replaceAll("_", " ")).join(", ")}. Check these details in Analysis.</p>}</div></details>}
    </Card>
    <ScoreBreakdown scores={deal.scores ?? {}} returnSchedule={analysis.return_schedule} />
    <ReturnContextPanel deal={deal} />
    <ReturnCrosscheckPanel check={analysis.return_crosscheck} />
    <ReturnSchedulePanel deal={deal} />
    <Card className="p-5 md:p-6"><h2 className="text-lg font-semibold">Capital, terms and operations</h2>
      {acceptedPaths.length === 0 && <p className="mt-3 text-sm text-muted-foreground">Add source documents to populate these terms. Open Questions for evidence that needs clarification.</p>}
      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{acceptedPaths.map(path => {
        const fact = facts[path];
        const label = path === "deal_structure.debt_amount" ? analysis.financing?.debt_amount_label ?? fact?.label : fact?.label;
        const context = operatingFactContext(fact);
        return <div key={path}><div className="text-xs text-muted-foreground">{label ?? path.split(".").pop()?.replaceAll("_", " ")}</div><div className="mt-1 text-lg font-semibold">{factValue(fact)}</div>{context && <p className="mt-1 text-xs text-muted-foreground">{context}</p>}<FactEvidence fact={fact} /></div>;
      })}</div>
      {pendingPaths.length > 0 && <details className="mt-4 border-t border-border pt-3 text-sm"><summary className="cursor-pointer text-muted-foreground">{pendingPaths.length} terms awaiting evidence</summary><div className="mt-3 grid gap-3 sm:grid-cols-2">{pendingPaths.map(path => <div key={path}><span className="text-xs text-muted-foreground">{facts[path]?.label ?? path.split(".").pop()?.replaceAll("_", " ")}</span><FactEvidence fact={facts[path]} /></div>)}</div></details>}
    </Card>
    {detailSections.map(({ prefix, title }) => {
      const entries = Object.entries(facts).filter(([path, fact]) => path.startsWith(prefix)
        && !acceptedPaths.includes(path) && !financingSourcePaths.has(path)
        && fact.value != null && ["checked", "calculated", "manual"].includes(fact.state));
      if (!entries.length) return null;
      return <Card key={prefix} className="p-5 md:p-6"><h2 className="text-lg font-semibold">{title}</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{entries.map(([path, fact]) => (
          <div key={path} className={typeof fact.value === "string" && fact.value.length > 100 ? "sm:col-span-2 lg:col-span-3" : ""}>
            <div className="text-xs text-muted-foreground">{fact.label}</div>
            <div className="mt-1 text-sm font-medium whitespace-pre-wrap break-words">{factValue(fact)}</div>
            {operatingFactContext(fact) && <p className="mt-1 text-xs text-muted-foreground">{operatingFactContext(fact)}</p>}
            <FactEvidence fact={fact} />
          </div>
        ))}</div>
      </Card>;
    })}
    <FinancingMeasuresPanel deal={deal} financing={analysis.financing} debtAmount={acceptedDebtAmount} />
    <p className="text-sm text-muted-foreground">Upload missing or newer evidence in <Link className="underline" href={`/deals/${deal.id}?tab=documents`}>Documents</Link>. Reported values, optional context, projections and audit details remain under Analysis.</p>
  </div>;
}
