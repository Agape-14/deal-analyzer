"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Calculator, CheckCircle2, FileText, Loader2, ShieldAlert } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { cn, fmtMoney, fmtMultiple, fmtPct } from "@/lib/utils";
import type { DealDetail, FieldProvenance, ValidationFlag } from "@/lib/types";

type ReviewArea = "Returns" | "Capital Stack" | "Debt" | "Construction" | "Sponsor" | "Market" | "Math" | "Source";
type Severity = "red" | "yellow";
type Metrics = NonNullable<DealDetail["metrics"]>;

type ReviewInput = {
  path: string;
  label: string;
  value: unknown;
  provenance?: FieldProvenance;
};

type ReviewItem = {
  key: string;
  priority: number;
  kind: "math" | "flag" | "source";
  area: ReviewArea;
  severity: Severity;
  title: string;
  detail: string;
  path?: string;
  value?: unknown;
  source?: string;
  inputs?: ReviewInput[];
  actionHref?: string;
  resolutionLabel?: string;
  reviewLabel?: string;
};

type MathCheck = { check?: string; difference?: string; formula?: string };

const REVIEW_LIMIT = 3;

const REVIEW_FIELDS = [
  { path: "target_returns.target_irr", label: "Target IRR", format: "pct" },
  { path: "target_returns.net_irr", label: "Net IRR", format: "pct" },
  { path: "target_returns.target_equity_multiple", label: "Target equity multiple", format: "multiple" },
  { path: "target_returns.net_equity_multiple", label: "Net equity multiple", format: "multiple" },
  { path: "target_returns.target_cash_on_cash", label: "Cash-on-cash", format: "pct" },
  { path: "target_returns.distribution_yield", label: "Distribution yield", format: "pct" },
  { path: "deal_structure.minimum_investment", label: "Minimum investment", format: "money" },
  { path: "deal_structure.total_project_cost", label: "Total project cost", format: "money" },
  { path: "deal_structure.total_equity_required", label: "Equity required", format: "money" },
  { path: "deal_structure.preferred_equity_amount", label: "Pref equity", format: "money" },
  { path: "deal_structure.debt_amount", label: "Debt amount", format: "money" },
  { path: "deal_structure.interest_rate", label: "Interest rate", format: "pct" },
  { path: "deal_structure.ltv", label: "LTV", format: "pct" },
  { path: "deal_structure.preferred_return", label: "Preferred return", format: "pct" },
  { path: "deal_structure.gp_equity_coinvest_pct", label: "GP co-invest", format: "pct" },
  { path: "deal_structure.gp_cash_at_risk", label: "GP cash at risk", format: "money" },
  { path: "deal_structure.gp_coinvest_is_rollover", label: "GP rollover?", format: "text" },
  { path: "deal_structure.gp_coinvest_description", label: "GP co-invest notes", format: "text" },
  { path: "financial_projections.stabilized_noi", label: "Stabilized NOI", format: "money" },
  { path: "financial_projections.entry_cap_rate", label: "Entry cap rate", format: "pct" },
  { path: "financial_projections.exit_cap_rate", label: "Exit cap rate", format: "pct" },
  { path: "financial_projections.avg_rent_per_unit", label: "Average rent", format: "money" },
  { path: "financial_projections.occupancy_assumption", label: "Occupancy", format: "pct" },
  { path: "financial_projections.rent_growth_assumption", label: "Rent growth", format: "pct" },
  { path: "financial_projections.operating_expense_ratio", label: "Expense ratio", format: "pct" },
  { path: "construction_costs.hard_costs", label: "Hard costs", format: "money" },
  { path: "construction_costs.hard_costs_total", label: "Hard costs total", format: "money" },
  { path: "construction_costs.soft_costs", label: "Soft costs", format: "money" },
  { path: "construction_costs.soft_costs_total", label: "Soft costs total", format: "money" },
  { path: "construction_costs.land_cost", label: "Land", format: "money" },
  { path: "construction_costs.land_cost_total", label: "Land total", format: "money" },
  { path: "construction_costs.contingency", label: "Contingency", format: "money" },
  { path: "construction_costs.contingency_total", label: "Contingency total", format: "money" },
  { path: "underwriting_checks.dscr", label: "DSCR", format: "multiple" },
  { path: "underwriting_checks.yield_on_cost", label: "Yield on cost", format: "pct" },
  { path: "underwriting_checks.break_even_occupancy", label: "Break-even occupancy", format: "pct" },
  { path: "sponsor_evaluation.alignment_score", label: "Alignment score", format: "integer" },
  { path: "sponsor_evaluation.sponsor_skin_in_game", label: "Sponsor skin in game", format: "text" },
  { path: "sponsor_evaluation.sponsor_full_cycle_deals", label: "Full-cycle deals", format: "integer" },
  { path: "sponsor_evaluation.sponsor_default_history", label: "Default history", format: "text" },
  { path: "project_details.unit_count", label: "Unit count", format: "integer" },
] as const;

const FALLBACK_INPUTS: Partial<Record<ReviewArea, Array<{ path: string; label: string }>>> = {
  Sponsor: [
    { path: "sponsor_evaluation.sponsor_full_cycle_deals", label: "Full-cycle deals" },
    { path: "sponsor_evaluation.sponsor_default_history", label: "Default history" },
    { path: "sponsor_evaluation.sponsor_skin_in_game", label: "Sponsor skin in game" },
    { path: "deal_structure.gp_cash_at_risk", label: "GP cash at risk" },
  ],
  Market: [
    { path: "market_location.market_rent_growth", label: "Market rent growth" },
    { path: "market_location.market_vacancy_rate", label: "Market vacancy" },
    { path: "financial_projections.rent_growth_assumption", label: "Rent growth" },
    { path: "financial_projections.occupancy_assumption", label: "Occupancy" },
  ],
  Returns: [
    { path: "target_returns.target_irr", label: "Target IRR" },
    { path: "target_returns.net_irr", label: "Net IRR" },
    { path: "target_returns.target_cash_on_cash", label: "Cash-on-cash" },
    { path: "target_returns.distribution_yield", label: "Distribution yield" },
    { path: "target_returns.target_equity_multiple", label: "Equity multiple" },
  ],
  "Capital Stack": [
    { path: "deal_structure.total_project_cost", label: "Total project cost" },
    { path: "deal_structure.total_equity_required", label: "Equity required" },
    { path: "deal_structure.preferred_equity_amount", label: "Pref equity" },
    { path: "deal_structure.debt_amount", label: "Debt" },
    { path: "deal_structure.preferred_return", label: "Preferred return" },
  ],
  Debt: [
    { path: "underwriting_checks.dscr", label: "DSCR" },
    { path: "deal_structure.ltv", label: "LTV" },
    { path: "deal_structure.debt_amount", label: "Debt" },
    { path: "deal_structure.interest_rate", label: "Interest rate" },
    { path: "financial_projections.stabilized_noi", label: "Stabilized NOI" },
  ],
  Construction: [
    { path: "construction_costs.hard_costs_total", label: "Hard costs total" },
    { path: "construction_costs.soft_costs_total", label: "Soft costs total" },
    { path: "construction_costs.land_cost_total", label: "Land total" },
    { path: "construction_costs.contingency_total", label: "Contingency total" },
    { path: "deal_structure.total_project_cost", label: "Total project cost" },
  ],
};

const CATEGORY_INPUTS: Record<string, Array<{ path: string; label: string }>> = {
  alignment: [
    { path: "deal_structure.gp_equity_coinvest_pct", label: "GP co-invest" },
    { path: "deal_structure.gp_cash_at_risk", label: "GP cash at risk" },
    { path: "deal_structure.gp_coinvest_is_rollover", label: "GP rollover?" },
    { path: "deal_structure.gp_coinvest_description", label: "GP co-invest notes" },
    { path: "sponsor_evaluation.alignment_score", label: "Alignment score" },
    { path: "sponsor_evaluation.sponsor_skin_in_game", label: "Sponsor skin in game" },
  ],
  underwriting: [
    { path: "underwriting_checks.dscr", label: "DSCR" },
    { path: "underwriting_checks.yield_on_cost", label: "Yield on cost" },
    { path: "financial_projections.entry_cap_rate", label: "Entry cap rate" },
    { path: "financial_projections.exit_cap_rate", label: "Exit cap rate" },
    { path: "financial_projections.occupancy_assumption", label: "Occupancy" },
    { path: "financial_projections.rent_growth_assumption", label: "Rent growth" },
    { path: "financial_projections.operating_expense_ratio", label: "Expense ratio" },
  ],
  structure: [
    { path: "deal_structure.preferred_return", label: "Preferred return" },
    { path: "deal_structure.promote_structure", label: "Promote structure" },
    { path: "deal_structure.waterfall_structure", label: "Waterfall" },
    { path: "deal_structure.fees_asset_mgmt", label: "Asset management fee" },
    { path: "deal_structure.fees_construction_mgmt", label: "Construction management fee" },
  ],
};

const MATH_INPUTS: Array<{ test: (name: string) => boolean; area: ReviewArea; primaryPath: string; inputs: Array<{ path: string; label: string }> }> = [
  {
    test: (name) => name.includes("dscr") || name.includes("debt service"),
    area: "Debt",
    primaryPath: "underwriting_checks.dscr",
    inputs: [
      { path: "underwriting_checks.dscr", label: "Reported DSCR" },
      { path: "financial_projections.stabilized_noi", label: "NOI" },
      { path: "deal_structure.debt_amount", label: "Debt" },
      { path: "deal_structure.interest_rate", label: "Rate" },
    ],
  },
  {
    test: (name) => name.includes("ltv"),
    area: "Debt",
    primaryPath: "deal_structure.ltv",
    inputs: [
      { path: "deal_structure.ltv", label: "Reported LTV" },
      { path: "deal_structure.debt_amount", label: "Debt" },
      { path: "deal_structure.total_project_cost", label: "Total cost" },
    ],
  },
  {
    test: (name) => name.includes("total project cost") && name.includes("equity"),
    area: "Capital Stack",
    primaryPath: "deal_structure.total_project_cost",
    inputs: [
      { path: "deal_structure.total_project_cost", label: "Total project cost" },
      { path: "deal_structure.total_equity_required", label: "Equity required" },
      { path: "deal_structure.preferred_equity_amount", label: "Pref equity" },
      { path: "deal_structure.debt_amount", label: "Debt" },
    ],
  },
  {
    test: (name) => name.includes("hard") && name.includes("soft") && name.includes("land"),
    area: "Construction",
    primaryPath: "deal_structure.total_project_cost",
    inputs: [
      { path: "construction_costs.hard_costs", label: "Hard costs" },
      { path: "construction_costs.hard_costs_total", label: "Hard costs total" },
      { path: "construction_costs.soft_costs", label: "Soft costs" },
      { path: "construction_costs.soft_costs_total", label: "Soft costs total" },
      { path: "construction_costs.land_cost", label: "Land" },
      { path: "construction_costs.land_cost_total", label: "Land total" },
      { path: "construction_costs.contingency", label: "Contingency" },
      { path: "construction_costs.contingency_total", label: "Contingency total" },
      { path: "deal_structure.total_project_cost", label: "Total cost" },
    ],
  },
  {
    test: (name) => name.includes("irr"),
    area: "Returns",
    primaryPath: "target_returns.target_irr",
    inputs: [
      { path: "target_returns.target_irr", label: "Target IRR" },
      { path: "target_returns.net_irr", label: "Net IRR" },
    ],
  },
  {
    test: (name) => name.includes("multiple"),
    area: "Returns",
    primaryPath: "target_returns.target_equity_multiple",
    inputs: [
      { path: "target_returns.target_equity_multiple", label: "Target equity multiple" },
      { path: "target_returns.net_equity_multiple", label: "Net equity multiple" },
    ],
  },
];

export function ReviewQueue({ deal }: { deal: DealDetail }) {
  const items = buildReviewItems(deal);
  const visible = items.slice(0, REVIEW_LIMIT);
  const hidden = items.slice(REVIEW_LIMIT);
  const groups = groupItems(hidden);

  if (items.length === 0) {
    return (
      <Card elevated className="p-6">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-lg bg-success/15 text-success ring-1 ring-success/30">
            <CheckCircle2 className="h-5 w-5" />
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Deal Readiness</div>
            <h3 className="text-base font-semibold tracking-tight">Ready to score</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">Every open review item has been corrected or confirmed.</p>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card elevated className="p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-lg bg-destructive/15 text-destructive ring-1 ring-destructive/30">
            <ShieldAlert className="h-5 w-5" />
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Deal Readiness</div>
            <h3 className="text-base font-semibold tracking-tight">Needs review</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {visible.length} priority item{visible.length === 1 ? "" : "s"} shown. Review values, fix bad numbers, or accept risk notes to clear them.
            </p>
          </div>
        </div>
        {hidden.length > 0 ? (
          <a href="#technical-details" className="text-xs text-muted-foreground transition-colors hover:text-foreground">
            {hidden.length} more grouped below
          </a>
        ) : null}
      </div>

      <div className="mt-5 space-y-3">
        {visible.map((item, index) => (
          <ReviewRow key={item.key} item={item} index={index} dealId={deal.id} />
        ))}
      </div>

      {groups.length > 0 ? (
        <div className="mt-5 border-t border-border/60 pt-4">
          <div className="mb-2 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">More issues by area</div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {groups.map((group) => (
              <a
                key={group.area}
                href="#technical-details"
                className="flex items-center justify-between rounded-lg border border-border/70 bg-muted/20 px-3 py-2 text-xs transition-colors hover:bg-muted/40"
              >
                <span className="font-medium text-foreground">{group.area}</span>
                <span className={cn("rounded-full px-2 py-0.5 font-semibold ring-1", group.red > 0 ? "bg-destructive/10 text-destructive ring-destructive/30" : "bg-warning/10 text-warning ring-warning/30")}>
                  {group.count}
                </span>
              </a>
            ))}
          </div>
        </div>
      ) : null}
    </Card>
  );
}

function ReviewRow({ item, index, dealId }: { item: ReviewItem; index: number; dealId: number }) {
  const Icon = item.kind === "math" ? Calculator : item.kind === "source" ? FileText : AlertTriangle;
  const [reviewingInputs, setReviewingInputs] = React.useState(false);
  const hasInputs = Boolean(item.inputs?.length);

  return (
    <div className="grid gap-3 rounded-lg border border-border/70 bg-card/40 p-4 md:grid-cols-[auto_1fr_auto] md:items-start">
      <div className={cn(
        "flex h-8 w-8 items-center justify-center rounded-md text-xs font-semibold ring-1 md:mt-1",
        item.severity === "red" ? "bg-destructive/15 text-destructive ring-destructive/30" : "bg-warning/15 text-warning ring-warning/30",
      )}>
        {index + 1}
      </div>

      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Icon className={cn("h-4 w-4", item.severity === "red" ? "text-destructive" : "text-warning")} />
          <div className="font-semibold tracking-tight">{item.title}</div>
          <span className="rounded-md bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground ring-1 ring-border/70">
            {item.area}
          </span>
        </div>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{item.detail}</p>
        {(item.value !== undefined || item.source) ? (
          <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
            {item.value !== undefined ? <span>Current: <span className="text-foreground">{formatReviewValue(item.value, item.path)}</span></span> : null}
            {item.source ? <span>Source: <span className="text-foreground">{item.source}</span></span> : null}
          </div>
        ) : null}
        {hasInputs ? (
          reviewingInputs ? (
            <ReviewInputEditor dealId={dealId} itemKey={item.key} inputs={item.inputs ?? []} onDone={() => setReviewingInputs(false)} />
          ) : (
            <ReviewInputSummary inputs={item.inputs ?? []} />
          )
        ) : null}
      </div>

      <ReviewActions
        item={item}
        dealId={dealId}
        reviewingInputs={reviewingInputs}
        onReviewInputs={hasInputs ? () => setReviewingInputs((value) => !value) : undefined}
      />
    </div>
  );
}

function ReviewActions({
  item,
  dealId,
  reviewingInputs,
  onReviewInputs,
}: {
  item: ReviewItem;
  dealId: number;
  reviewingInputs?: boolean;
  onReviewInputs?: () => void;
}) {
  const router = useRouter();
  const [busy, setBusy] = React.useState(false);

  async function confirmReviewItem() {
    setBusy(true);
    try {
      await api.post(`/api/deals/${dealId}/fields/edit`, {
        path: reviewResolutionPath(item.key),
        value: true,
        lock: true,
      });
      toast.success("Review item confirmed", { description: "Removed from Needs review." });
      router.refresh();
    } catch (e) {
      toast.error("Could not confirm review item", { description: errorDetail(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 md:justify-end md:pt-8">
      <Button size="sm" onClick={confirmReviewItem} disabled={busy}>
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
        {item.resolutionLabel ?? "Confirm"}
      </Button>
      {onReviewInputs ? (
        <Button size="sm" variant={reviewingInputs ? "secondary" : "outline"} onClick={onReviewInputs} disabled={busy}>
          {reviewingInputs ? "Hide values" : item.reviewLabel ?? "Review values"}
        </Button>
      ) : null}
      {item.actionHref ? (
        <Button size="sm" variant="outline" asChild>
          <a href={item.actionHref}>Open source</a>
        </Button>
      ) : null}
    </div>
  );
}

function ReviewInputSummary({ inputs }: { inputs: ReviewInput[] }) {
  const visible = inputs.slice(0, 8);
  return (
    <div className="mt-3 rounded-lg border border-border/70 bg-muted/20 p-2.5">
      <div className="mb-1.5 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Inputs to check</div>
      <div className="flex flex-wrap gap-1.5">
        {visible.map((input) => (
          <span key={input.path} className="rounded-md border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground">
            {input.label}: <span className="font-medium text-foreground">{formatReviewValue(input.value, input.path)}</span>
          </span>
        ))}
        {inputs.length > visible.length ? (
          <span className="rounded-md border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground">
            +{inputs.length - visible.length} more
          </span>
        ) : null}
      </div>
    </div>
  );
}

function ReviewInputEditor({ dealId, itemKey, inputs, onDone }: { dealId: number; itemKey: string; inputs: ReviewInput[]; onDone?: () => void }) {
  const router = useRouter();
  const editableInputs = inputs.filter((input) => isEditableReviewInput(input));
  const [drafts, setDrafts] = React.useState<Record<string, string>>(() =>
    Object.fromEntries(editableInputs.map((input) => [input.path, scalarToInput(input.value)])),
  );
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    setDrafts(Object.fromEntries(editableInputs.map((input) => [input.path, scalarToInput(input.value)])));
  }, [inputs]);

  async function saveAll() {
    const edits = editableInputs
      .map((input) => {
        const draft = drafts[input.path] ?? "";
        return draft.trim() === "" ? null : { path: input.path, value: parseDraftValue(draft, input.value), lock: true };
      })
      .filter((edit): edit is { path: string; value: string | number | boolean | null; lock: boolean } => edit !== null);

    if (edits.length === 0) {
      toast.error("Nothing to save", { description: "Enter or confirm at least one value." });
      return;
    }

    setBusy(true);
    try {
      for (const edit of edits) {
        await api.post(`/api/deals/${dealId}/fields/edit`, edit);
      }
      await api.post(`/api/deals/${dealId}/fields/edit`, {
        path: reviewResolutionPath(itemKey),
        value: true,
        lock: true,
      });
      toast.success("Inputs saved and review item cleared", { description: `${edits.length} field${edits.length === 1 ? "" : "s"} updated.` });
      onDone?.();
      router.refresh();
    } catch (e) {
      toast.error("Could not save inputs", { description: errorDetail(e) });
    } finally {
      setBusy(false);
    }
  }

  if (editableInputs.length === 0) return null;

  return (
    <div className="mt-3 rounded-lg border border-primary/25 bg-primary/5 p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-semibold tracking-tight text-foreground">Review values for this issue</div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">Edit wrong values here, or leave them unchanged and save to approve this row.</p>
        </div>
        <Button size="sm" onClick={saveAll} disabled={busy}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
          Save and clear
        </Button>
      </div>
      <div className="grid gap-2 lg:grid-cols-2">
        {editableInputs.map((input) => (
          <div key={input.path} className="rounded-md border border-border/70 bg-background/70 p-2">
            <div className="mb-1 flex items-center justify-between gap-2">
              <div className="text-[11px] font-medium text-muted-foreground">{input.label}</div>
              <a href={sourceHref(input.path)} className="text-[11px] text-primary hover:underline">
                source
              </a>
            </div>
            <div className="flex items-center gap-2">
              <input
                value={drafts[input.path] ?? ""}
                onChange={(e) => setDrafts((prev) => ({ ...prev, [input.path]: e.target.value }))}
                placeholder="missing or 65.95M"
                className="h-8 min-w-0 flex-1 rounded-md border border-border bg-background px-2 text-xs outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
            <div className="mt-1 text-[10px] text-muted-foreground">{input.path}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function buildReviewItems(deal: DealDetail): ReviewItem[] {
  const metrics = (deal.metrics ?? {}) as Metrics;
  const gate = (deal.scores?.data_quality ?? (metrics as Record<string, unknown>)._data_quality) as any;
  const provenance = (((metrics as Record<string, unknown>)._provenance ?? {}) as Record<string, FieldProvenance>);
  const flags = (Array.isArray((metrics as any).validation_flags) ? (metrics as any).validation_flags : []) as ValidationFlag[];
  const items: ReviewItem[] = [];

  items.push(...mathItems(gate, metrics, provenance));
  items.push(...flagItems(flags, metrics, provenance));
  items.push(...sourceItems(metrics, provenance));

  return dedupeItems(items)
    .filter((item) => !isReviewResolved(metrics, item.key))
    .sort((a, b) => b.priority - a.priority)
    .slice(0, 12);
}

function mathItems(gate: any, metrics: Metrics, provenance: Record<string, FieldProvenance>): ReviewItem[] {
  const checks = ((gate?.math_summary?.blocking ?? []) as MathCheck[]).filter((check) => !mathCheckPassesNow(check, metrics));
  return checks.map((check, index) => {
    const config = findMathConfig(check.check ?? "");
    const inputs = config?.inputs
      .map((input) => ({ ...input, value: getPath(metrics, input.path), provenance: provenance[input.path] }))
      .filter((input, pos, arr) => arr.findIndex((candidate) => candidate.path === input.path) === pos);
    return {
      key: `math:${check.check ?? index}`,
      priority: 100 - index,
      kind: "math" as const,
      area: config?.area ?? "Math",
      severity: "red" as const,
      title: check.check || "Math check failed",
      detail: [check.difference, check.formula].filter(Boolean).join(" - ") || "A saved calculation does not reconcile.",
      path: config?.primaryPath,
      value: config?.primaryPath ? getPath(metrics, config.primaryPath) : undefined,
      source: config?.primaryPath ? sourceLabel(provenance[config.primaryPath]) : undefined,
      inputs,
      actionHref: config?.primaryPath ? sourceHref(config.primaryPath) : "#technical-details",
    };
  });
}

function flagItems(flags: ValidationFlag[], metrics: Metrics, provenance: Record<string, FieldProvenance>): ReviewItem[] {
  return flags
    .filter((flag) => ["red", "yellow"].includes(String(flag.severity).toLowerCase()))
    .map((flag, index) => {
      const path = extractBestPath(flag.message);
      const area = areaForFlag(flag, path);
      const inputs = reviewInputsForMessage(flag.message, path, metrics, provenance) ?? fallbackInputsForFlag(flag, area, metrics, provenance);
      const sourcePath = path ?? firstSourcedInputPath(inputs, provenance);
      const isQualitative = !path && inputs && inputs.length > 0;
      return {
        key: `flag:${flag.category}:${path ?? flag.message}`,
        priority: flag.severity === "red" ? 80 - index : 45 - index,
        kind: "flag" as const,
        area,
        severity: flag.severity === "red" ? "red" as const : "yellow" as const,
        title: path ? `${humanizePath(path)} needs review` : `${flag.category} risk note`,
        detail: simplifyMessage(flag.message),
        path,
        value: path ? getPath(metrics, path) : undefined,
        source: path ? sourceLabel(provenance[path]) : undefined,
        inputs,
        actionHref: sourcePath ? sourceHref(sourcePath) : undefined,
        resolutionLabel: isQualitative ? "Accept risk note" : "Confirm",
        reviewLabel: isQualitative ? "Review related values" : "Review values",
      };
    });
}

function sourceItems(metrics: Metrics, provenance: Record<string, FieldProvenance>): ReviewItem[] {
  const out: ReviewItem[] = [];
  for (const field of REVIEW_FIELDS) {
    const prov = provenance[field.path];
    const value = getPath(metrics, field.path);
    if (!prov || prov.locked) continue;
    const status = String(prov.status ?? "").toLowerCase();
    const confidence = typeof prov.confidence === "number" ? prov.confidence : null;
    const conflictCount = Array.isArray(prov.conflict) ? prov.conflict.length : 0;
    const needsReview = conflictCount > 1 || ["wrong", "missing", "unverifiable", "stale"].includes(status) || (confidence !== null && confidence < 85);
    if (!needsReview) continue;
    out.push({
      key: `source:${field.path}`,
      priority: conflictCount > 1 || status === "wrong" ? 75 : confidence !== null ? 40 - confidence / 10 : 35,
      kind: "source",
      area: areaForPath(field.path),
      severity: conflictCount > 1 || status === "wrong" || status === "missing" ? "red" : "yellow",
      title: `${field.label} needs review`,
      detail: sourceDetail(prov),
      path: field.path,
      value,
      source: sourceLabel(prov),
      inputs: [{ path: field.path, label: field.label, value, provenance: prov }],
      actionHref: sourceHref(field.path),
    });
  }
  return out;
}

function reviewInputsForMessage(message: string, primaryPath: string | undefined, metrics: Metrics, provenance: Record<string, FieldProvenance>): ReviewInput[] | undefined {
  const paths = new Set<string>();
  if (primaryPath) paths.add(primaryPath);
  for (const path of message.match(/[a-z_]+\.[a-z_]+/g) ?? []) {
    if (REVIEW_FIELDS.some((field) => field.path === path)) paths.add(path);
  }
  const inputs = Array.from(paths).map((path) => ({
    path,
    label: humanizePath(path),
    value: getPath(metrics, path),
    provenance: provenance[path],
  }));
  return inputs.length > 0 ? inputs : undefined;
}

function fallbackInputsForFlag(
  flag: ValidationFlag,
  area: ReviewArea,
  metrics: Metrics,
  provenance: Record<string, FieldProvenance>,
): ReviewInput[] | undefined {
  const category = String(flag.category ?? "").toLowerCase();
  const definitions = CATEGORY_INPUTS[category] ?? FALLBACK_INPUTS[area];
  if (!definitions?.length) return undefined;
  const inputs = definitions
    .map((input) => ({ ...input, value: getPath(metrics, input.path), provenance: provenance[input.path] }))
    .filter((input, pos, arr) => arr.findIndex((candidate) => candidate.path === input.path) === pos);
  return inputs.length > 0 ? inputs : undefined;
}

function firstSourcedInputPath(inputs: ReviewInput[] | undefined, provenance: Record<string, FieldProvenance>): string | undefined {
  return (
    inputs?.find((input) => provenance[input.path]?.source_doc_name)?.path ??
    inputs?.find((input) => input.value !== null && input.value !== undefined && input.value !== "")?.path
  );
}

function findMathConfig(checkName: string) {
  const name = normalizeMathName(checkName);
  return MATH_INPUTS.find((config) => config.test(name));
}

function normalizeMathName(name: string): string {
  return name.toLowerCase().replace(/\s+/g, " ").trim();
}

function mathCheckPassesNow(check: MathCheck, metrics: Metrics): boolean {
  const name = normalizeMathName(check.check ?? "");
  if (name.includes("dscr") || name.includes("debt service")) {
    const reported = numberValue(getPath(metrics, "underwriting_checks.dscr"));
    const noi = numberValue(getPath(metrics, "financial_projections.stabilized_noi"));
    const debt = numberValue(getPath(metrics, "deal_structure.debt_amount"));
    const rate = numberValue(getPath(metrics, "deal_structure.interest_rate"));
    if (reported === null || noi === null || debt === null || rate === null || rate <= 0) return false;
    return Math.abs(noi / (debt * (rate / 100)) - reported) < 0.05;
  }
  if (name.includes("ltv")) return valuesWithinFormula(metrics, "deal_structure.ltv", "deal_structure.debt_amount", "deal_structure.total_project_cost", 0.5, 100);
  if (name.includes("irr")) return valuesWithin(metrics, "target_returns.target_irr", "target_returns.net_irr", 0.25);
  if (name.includes("multiple")) return valuesWithin(metrics, "target_returns.target_equity_multiple", "target_returns.net_equity_multiple", 0.02);
  return false;
}

function valuesWithin(metrics: Metrics, leftPath: string, rightPath: string, tolerance: number): boolean {
  const left = numberValue(getPath(metrics, leftPath));
  const right = numberValue(getPath(metrics, rightPath));
  return left !== null && right !== null && Math.abs(left - right) <= tolerance;
}

function valuesWithinFormula(metrics: Metrics, reportedPath: string, numeratorPath: string, denominatorPath: string, tolerance: number, multiplier = 1): boolean {
  const reported = numberValue(getPath(metrics, reportedPath));
  const numerator = numberValue(getPath(metrics, numeratorPath));
  const denominator = numberValue(getPath(metrics, denominatorPath));
  return reported !== null && numerator !== null && denominator !== null && denominator > 0 && Math.abs((numerator / denominator) * multiplier - reported) <= tolerance;
}

function extractBestPath(message: string): string | undefined {
  const matches = message.match(/[a-z_]+\.[a-z_]+/g) ?? [];
  return matches.find((path) => path.includes("target_")) ?? matches.find((path) => path.includes("net_")) ?? matches[0];
}

function simplifyMessage(message: string): string {
  return message.length <= 190 ? message : `${message.slice(0, 187)}...`;
}

function sourceDetail(provenance: FieldProvenance): string {
  if (Array.isArray(provenance.conflict) && provenance.conflict.length > 1) return "Documents disagree. Confirm the right value or edit it.";
  if (provenance.status === "wrong") return "Verification challenged this value. Confirm it or edit the field.";
  if (provenance.status === "missing") return "This required field is missing from the extracted data.";
  if (provenance.status === "unverifiable") return "The verifier could not tie this value back to a source document.";
  if (typeof provenance.confidence === "number") return `Confidence is ${provenance.confidence}%, below the 85% review threshold.`;
  return "This value needs human review before it can be trusted.";
}

function sourceLabel(provenance?: FieldProvenance): string | undefined {
  if (!provenance?.source_doc_name) return undefined;
  return `${provenance.source_doc_name}${provenance.source_page ? ` p.${provenance.source_page}` : ""}`;
}

function sourceHref(path: string): string {
  return `#${sourceCitationId(path)}`;
}

function areaForFlag(flag: ValidationFlag, path?: string): ReviewArea {
  const cat = String(flag.category ?? "").toLowerCase();
  if (cat.includes("return") || path?.startsWith("target_returns")) return "Returns";
  if (cat.includes("leverage") || cat.includes("debt") || path?.includes("debt") || path?.includes("ltv")) return "Debt";
  if (cat.includes("sponsor") || cat.includes("alignment")) return "Sponsor";
  if (cat.includes("market")) return "Market";
  if (cat.includes("source")) return "Source";
  if (cat.includes("benchmark") || cat.includes("underwriting")) return "Capital Stack";
  return path ? areaForPath(path) : "Source";
}

function areaForPath(path: string): ReviewArea {
  if (path.startsWith("target_returns")) return "Returns";
  if (path.includes("debt") || path.includes("ltv") || path.includes("dscr")) return "Debt";
  if (path.startsWith("construction_costs")) return "Construction";
  if (path.startsWith("sponsor_evaluation")) return "Sponsor";
  if (path.startsWith("market_location")) return "Market";
  return "Capital Stack";
}

function groupItems(items: ReviewItem[]) {
  const by = new Map<ReviewArea, { area: ReviewArea; count: number; red: number }>();
  for (const item of items) {
    const group = by.get(item.area) ?? { area: item.area, count: 0, red: 0 };
    group.count += 1;
    if (item.severity === "red") group.red += 1;
    by.set(item.area, group);
  }
  return Array.from(by.values()).sort((a, b) => b.red - a.red || b.count - a.count);
}

function dedupeItems(items: ReviewItem[]): ReviewItem[] {
  const byKey = new Map<string, ReviewItem>();
  for (const item of items) {
    const key = item.path ?? item.key;
    const existing = byKey.get(key);
    if (!existing || item.priority > existing.priority) byKey.set(key, item);
  }
  return Array.from(byKey.values());
}

function reviewResolutionKey(key: string): string {
  return encodeURIComponent(key).replace(/\./g, "%2E");
}

function reviewResolutionPath(key: string): string {
  return `_review_resolutions.${reviewResolutionKey(key)}`;
}

function isReviewResolved(metrics: Metrics, key: string): boolean {
  const resolved = (metrics as Record<string, unknown>)._review_resolutions;
  if (!resolved || typeof resolved !== "object") return false;
  return Boolean((resolved as Record<string, unknown>)[reviewResolutionKey(key)]);
}

function getPath(data: unknown, path?: string): unknown {
  if (!path) return undefined;
  let cur = data;
  for (const part of path.split(".")) {
    if (!cur || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[part];
  }
  return cur;
}

function numberValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value.replace(/[$,%x]/gi, "").replace(/,/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function sourceCitationId(path: string): string {
  return `source-citation-${path.replace(/[^a-zA-Z0-9_-]+/g, "-")}`;
}

function isEditableReviewInput(input: ReviewInput): boolean {
  return input.value == null || ["string", "number", "boolean"].includes(typeof input.value);
}

function formatReviewValue(value: unknown, path?: string): string {
  if (value == null || value === "") return "missing";
  const n = typeof value === "number" ? value : typeof value === "string" && !Number.isNaN(Number(value)) ? Number(value) : null;
  if (n == null) return String(value);
  const field = REVIEW_FIELDS.find((f) => f.path === path);
  switch (field?.format) {
    case "pct":
      return fmtPct(n, 1);
    case "money":
      return fmtMoney(n);
    case "multiple":
      return fmtMultiple(n);
    case "integer":
      return Math.round(n).toLocaleString();
    default:
      return String(value);
  }
}

function scalarToInput(value: unknown): string {
  if (value == null) return "";
  if (["string", "number", "boolean"].includes(typeof value)) return String(value);
  return "";
}

function parseDraftValue(value: string, original: unknown): string | number | boolean | null {
  const raw = value.trim();
  if (raw === "") return null;
  const compact = raw.replace(/[$,%x]/gi, "").replace(/,/g, "").trim();
  if (typeof original === "boolean") return ["true", "1", "yes"].includes(compact.toLowerCase());
  const numeric = compact.match(/^(-?\d+(?:\.\d+)?)(k|mm|m|b)?$/i);
  if (numeric) {
    const [, amount, suffix = ""] = numeric;
    const multipliers: Record<string, number> = { k: 1_000, m: 1_000_000, mm: 1_000_000, b: 1_000_000_000 };
    return Number(amount) * (multipliers[suffix.toLowerCase()] ?? 1);
  }
  return raw;
}

function errorDetail(error: unknown): string {
  if (!error) return "The server did not return a reason.";
  const detail = (error as { detail?: unknown; message?: unknown })?.detail ?? (error as { message?: unknown })?.message;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (detail && typeof detail === "object") {
    try {
      return JSON.stringify(detail);
    } catch {
      return "The server returned an unreadable error.";
    }
  }
  return "The server did not return a reason.";
}

function humanizePath(path: string): string {
  const field = path.split(".").at(-1) ?? path;
  const label = REVIEW_FIELDS.find((item) => item.path === path)?.label;
  return label ?? field.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}
