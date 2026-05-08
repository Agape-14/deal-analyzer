"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Calculator, CheckCircle2, FileText, Loader2, Pencil, ShieldAlert } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { FieldReviewAction } from "@/components/deal-detail/field-review-action";
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
  provenance?: FieldProvenance;
  source?: string;
  recommendedValue?: string | number | boolean | null;
  recommendedLabel?: string;
  inputs?: ReviewInput[];
  actionHref?: string;
  actionLabel?: string;
};

type MathCheck = { check?: string; difference?: string; formula?: string };

type MathConfig = {
  test: (name: string) => boolean;
  primaryPath: string;
  area: ReviewArea;
  inputs: Array<{ path: string; label: string }>;
};

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
  { path: "financial_projections.stabilized_noi", label: "Stabilized NOI", format: "money" },
  { path: "financial_projections.avg_rent_per_unit", label: "Average rent", format: "money" },
  { path: "financial_projections.occupancy_assumption", label: "Occupancy", format: "pct" },
  { path: "construction_costs.hard_costs", label: "Hard costs", format: "money" },
  { path: "construction_costs.hard_costs_total", label: "Hard costs total", format: "money" },
  { path: "construction_costs.soft_costs", label: "Soft costs", format: "money" },
  { path: "construction_costs.soft_costs_total", label: "Soft costs total", format: "money" },
  { path: "construction_costs.land_cost", label: "Land", format: "money" },
  { path: "construction_costs.land_cost_total", label: "Land total", format: "money" },
  { path: "construction_costs.contingency", label: "Contingency", format: "money" },
  { path: "construction_costs.contingency_total", label: "Contingency total", format: "money" },
  { path: "underwriting_checks.dscr", label: "DSCR", format: "multiple" },
  { path: "project_details.unit_count", label: "Unit count", format: "integer" },
] as const;

const MATH_CONFIGS: MathConfig[] = [
  {
    test: (name) => name === "target irr = net irr",
    primaryPath: "target_returns.target_irr",
    area: "Returns",
    inputs: [
      { path: "target_returns.target_irr", label: "Target IRR" },
      { path: "target_returns.net_irr", label: "Net IRR" },
    ],
  },
  {
    test: (name) => name === "equity multiple = net equity multiple",
    primaryPath: "target_returns.target_equity_multiple",
    area: "Returns",
    inputs: [
      { path: "target_returns.target_equity_multiple", label: "Target equity multiple" },
      { path: "target_returns.net_equity_multiple", label: "Net equity multiple" },
    ],
  },
  {
    test: (name) => name === "cash-on-cash = distribution yield",
    primaryPath: "target_returns.target_cash_on_cash",
    area: "Returns",
    inputs: [
      { path: "target_returns.target_cash_on_cash", label: "Cash-on-cash" },
      { path: "target_returns.distribution_yield", label: "Distribution yield" },
    ],
  },
  {
    test: (name) => name.includes("dscr") || name.includes("debt service"),
    primaryPath: "underwriting_checks.dscr",
    area: "Debt",
    inputs: [
      { path: "underwriting_checks.dscr", label: "Reported DSCR" },
      { path: "financial_projections.stabilized_noi", label: "NOI" },
      { path: "deal_structure.debt_amount", label: "Debt" },
      { path: "deal_structure.interest_rate", label: "Rate" },
    ],
  },
  {
    test: (name) => name === "ltv = debt / total cost",
    primaryPath: "deal_structure.ltv",
    area: "Debt",
    inputs: [
      { path: "deal_structure.ltv", label: "Reported LTV" },
      { path: "deal_structure.debt_amount", label: "Debt" },
      { path: "deal_structure.total_project_cost", label: "Total cost" },
    ],
  },
  {
    test: (name) => name === "total project cost = equity + debt" || name === "total project cost = equity + debt + pref equity",
    primaryPath: "deal_structure.total_project_cost",
    area: "Capital Stack",
    inputs: [
      { path: "deal_structure.total_project_cost", label: "Total project cost" },
      { path: "deal_structure.total_equity_required", label: "Equity required" },
      { path: "deal_structure.preferred_equity_amount", label: "Pref equity" },
      { path: "deal_structure.debt_amount", label: "Debt" },
    ],
  },
  {
    test: (name) => name.includes("hard") && name.includes("soft") && name.includes("land") && name.includes("contingency"),
    primaryPath: "deal_structure.total_project_cost",
    area: "Construction",
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
            <p className="mt-0.5 text-xs text-muted-foreground">All critical values are sourced, verified, and math-checked.</p>
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
              {visible.length} priority item{visible.length === 1 ? "" : "s"} shown. Correct or approve these before trusting the score.
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
  const hasInputs = Boolean(item.inputs?.length);
  const [reviewingInputs, setReviewingInputs] = React.useState(false);
  const [savedInputs, setSavedInputs] = React.useState(false);

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
        {item.inputs && item.inputs.length > 0 && reviewingInputs ? (
          <ReviewInputEditor
            dealId={dealId}
            inputs={item.inputs}
            onSaved={() => {
              setSavedInputs(true);
              setReviewingInputs(false);
            }}
          />
        ) : hasInputs ? (
          <ReviewInputSummary inputs={item.inputs ?? []} saved={savedInputs} />
        ) : null}
        {(item.value !== undefined || item.recommendedValue !== undefined || item.source) ? (
          <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
            {item.value !== undefined ? <span>Current: <span className="text-foreground">{formatReviewValue(item.value, item.path)}</span></span> : null}
            {item.recommendedValue !== undefined ? <span>Recommended: <span className="text-foreground">{formatReviewValue(item.recommendedValue, item.path)}</span></span> : null}
            {item.source ? <span>Source: <span className="text-foreground">{item.source}</span></span> : null}
          </div>
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

function ReviewInputSummary({ inputs, saved }: { inputs: ReviewInput[]; saved: boolean }) {
  const visible = inputs.slice(0, 8);
  return (
    <div className="mt-3 rounded-lg border border-border/70 bg-muted/20 p-2.5">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Inputs to check</div>
        {saved ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-success/10 px-2 py-0.5 text-[10px] font-medium text-success ring-1 ring-success/25">
            <CheckCircle2 className="h-3 w-3" />
            Saved
          </span>
        ) : null}
      </div>
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
      {saved ? (
        <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
          Saved. If this row remains after refresh, the stored values still do not reconcile or the source needs approval.
        </p>
      ) : null}
    </div>
  );
}

function ReviewInputEditor({ dealId, inputs, onSaved }: { dealId: number; inputs: ReviewInput[]; onSaved?: () => void }) {
  const router = useRouter();
  const editableInputs = inputs.filter((input) => isEditableReviewInput(input));
  const [drafts, setDrafts] = React.useState<Record<string, string>>(() =>
    Object.fromEntries(editableInputs.map((input) => [input.path, scalarToInput(input.value)])),
  );
  const [busyPath, setBusyPath] = React.useState<string | null>(null);

  React.useEffect(() => {
    setDrafts(Object.fromEntries(editableInputs.map((input) => [input.path, scalarToInput(input.value)])));
  }, [inputs]);

  if (editableInputs.length === 0) return null;

  async function saveInput(input: ReviewInput) {
    const draft = drafts[input.path] ?? "";
    if (draft.trim() === "") {
      toast.error("Enter a value before saving", { description: humanizePath(input.path) });
      return;
    }
    setBusyPath(input.path);
    try {
      await api.post(`/api/deals/${dealId}/fields/edit`, {
        path: input.path,
        value: parseDraftValue(draft, input.value),
        lock: true,
      });
      toast.success("Input saved and checks updated", { description: humanizePath(input.path) });
      onSaved?.();
      router.refresh();
    } catch (e) {
      toast.error(`Could not save ${humanizePath(input.path)}`, { description: errorDetail(e) });
    } finally {
      setBusyPath(null);
    }
  }

  async function saveAll() {
    const edits = editableInputs
      .map((input) => {
        const draft = drafts[input.path] ?? "";
        return draft.trim() === ""
          ? null
          : { path: input.path, value: parseDraftValue(draft, input.value), lock: true };
      })
      .filter((edit): edit is { path: string; value: string | number | boolean | null; lock: boolean } => edit !== null);

    if (edits.length === 0) {
      toast.error("Nothing to save", { description: "Enter at least one value, then save again." });
      return;
    }

    setBusyPath("__all");
    try {
      await api.post(`/api/deals/${dealId}/fields/batch-edit`, { edits });
      toast.success("Inputs saved and checks updated", { description: `${edits.length} field${edits.length === 1 ? "" : "s"} updated and locked` });
      onSaved?.();
      router.refresh();
    } catch (e) {
      toast.error("Could not save inputs", { description: errorDetail(e) });
    } finally {
      setBusyPath(null);
    }
  }

  return (
    <div className="mt-3 rounded-lg border border-primary/25 bg-primary/5 p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-semibold tracking-tight text-foreground">Review and correct inputs</div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">Edit any value that looks wrong. If a value is correct, leave it unchanged and save to approve it.</p>
        </div>
        <Button size="sm" onClick={saveAll} disabled={busyPath !== null}>
          {busyPath === "__all" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
          Save/approve all
        </Button>
      </div>
      <div className="grid gap-2 lg:grid-cols-2">
        {editableInputs.map((input) => (
          <div key={input.path} className="rounded-md border border-border/70 bg-background/70 p-2">
            <div className="mb-1 flex items-center justify-between gap-2">
              <div className="text-[11px] font-medium text-muted-foreground">{input.label}</div>
              <a
                href={sourceHref(input.provenance, input.path)}
                target={input.provenance?.source_doc_id ? "_blank" : undefined}
                rel={input.provenance?.source_doc_id ? "noreferrer" : undefined}
                className="text-[11px] text-primary hover:underline"
              >
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
              <Button size="sm" variant="secondary" onClick={() => saveInput(input)} disabled={busyPath !== null}>
                {busyPath === input.path ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                Save/approve
              </Button>
            </div>
            <div className="mt-1 text-[10px] text-muted-foreground">{input.path}</div>
          </div>
        ))}
      </div>
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
  const [busy, setBusy] = React.useState<"apply" | "save" | null>(null);
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(() => scalarToInput(item.value));
  const hasInlineEditor = Boolean(item.inputs?.length);
  const canEdit = Boolean(item.path) && !hasInlineEditor;
  const actionHref = item.actionHref ?? (item.path ? sourceHref(item.provenance, item.path) : "#technical-details");
  const actionLabel = item.actionLabel ?? "View source";

  async function saveValue(value: unknown, mode: "apply" | "save") {
    if (!item.path) return;
    setBusy(mode);
    try {
      await api.post(`/api/deals/${dealId}/fields/edit`, { path: item.path, value, lock: true });
      toast.success(mode === "apply" ? "Recommended fix applied" : "Field saved and checks updated", {
        description: humanizePath(item.path),
      });
      setEditing(false);
      router.refresh();
    } catch (e) {
      toast.error("Could not update field", { description: errorDetail(e) });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 md:justify-end md:pt-8">
      {onReviewInputs ? (
        <Button size="sm" variant={reviewingInputs ? "secondary" : "outline"} onClick={onReviewInputs}>
          {reviewingInputs ? "Hide inputs" : "Review inputs"}
        </Button>
      ) : null}
      {item.recommendedValue !== undefined && item.path ? (
        <Button size="sm" onClick={() => saveValue(item.recommendedValue, "apply")} disabled={busy !== null}>
          {busy === "apply" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
          {item.recommendedLabel ?? "Apply fix"}
        </Button>
      ) : null}
      {canEdit && !editing ? (
        <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
          <Pencil className="h-3.5 w-3.5" />
          Edit
        </Button>
      ) : null}
      {!hasInlineEditor && item.path && item.provenance ? (
        <FieldReviewAction dealId={dealId} path={item.path} value={item.value} provenance={item.provenance} />
      ) : null}
      <Button size="sm" variant="outline" asChild>
        <a href={actionHref} target={item.provenance?.source_doc_id ? "_blank" : undefined} rel={item.provenance?.source_doc_id ? "noreferrer" : undefined}>{actionLabel}</a>
      </Button>
      {editing && item.path ? (
        <div className="flex w-full items-center gap-2 md:w-auto">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="h-8 min-w-28 rounded-md border border-border bg-background px-2 text-xs outline-none focus:ring-2 focus:ring-ring"
          />
          <Button size="sm" onClick={() => saveValue(parseDraftValue(draft, item.value), "save")} disabled={busy !== null}>
            {busy === "save" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Save
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setEditing(false)} disabled={busy !== null}>
            Cancel
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function buildReviewItems(deal: DealDetail): ReviewItem[] {
  const metrics = (deal.metrics ?? {}) as Metrics;
  const gate = (deal.scores?.data_quality ?? (metrics as any)._data_quality) as any;
  const provenance = (((metrics as any)._provenance ?? {}) as Record<string, FieldProvenance>);
  const flags = (Array.isArray((metrics as any).validation_flags) ? (metrics as any).validation_flags : []) as ValidationFlag[];
  const items: ReviewItem[] = [];

  items.push(...mathItems(gate, metrics, provenance));
  items.push(...flagItems(flags, metrics, provenance));
  items.push(...sourceItems(metrics, provenance));

  return dedupeItems(items).sort((a, b) => b.priority - a.priority).slice(0, 12);
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
      detail: mathDetail(check, metrics),
      path: config?.primaryPath,
      value: config?.primaryPath ? getPath(metrics, config.primaryPath) : undefined,
      provenance: config?.primaryPath ? provenance[config.primaryPath] : undefined,
      inputs,
      actionHref: config?.primaryPath ? sourceHref(provenance[config.primaryPath], config.primaryPath) : "#technical-details",
      actionLabel: "Open source",
    };
  });
}

function flagItems(flags: ValidationFlag[], metrics: Metrics, provenance: Record<string, FieldProvenance>): ReviewItem[] {
  return flags
    .filter((flag) => ["red", "yellow"].includes(String(flag.severity).toLowerCase()))
    .map((flag, index) => {
      const alias = aliasRecommendation(flag.message);
      const path = alias?.path ?? extractBestPath(flag.message);
      const inputs = reviewInputsForFlag(flag.message, path, metrics, provenance);
      return {
        key: `flag:${flag.category}:${path ?? flag.message}`,
        priority: flag.severity === "red" ? 80 - index : 45 - index,
        kind: "flag" as const,
        area: areaForFlag(flag, path),
        severity: flag.severity === "red" ? "red" as const : "yellow" as const,
        title: flagTitle(flag, path),
        detail: simplifyMessage(flag.message),
        path,
        value: path ? getPath(metrics, path) : undefined,
        provenance: path ? provenance[path] : undefined,
        source: path ? sourceLabel(provenance[path]) : undefined,
        recommendedValue: alias?.value,
        recommendedLabel: alias?.label,
        inputs,
        actionHref: path ? sourceHref(provenance[path], path) : "#source-citations",
        actionLabel: path ? "Open source" : "Review sources",
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
      provenance: prov,
      source: sourceLabel(prov),
      inputs: [{ path: field.path, label: field.label, value, provenance: prov }],
      actionHref: sourceHref(prov, field.path),
      actionLabel: prov.source_doc_id ? "Open document" : "View citation",
    });
  }
  return out;
}

function mathCheckPassesNow(check: MathCheck, metrics: Metrics): boolean {
  const name = normalizeMathName(check.check ?? "");

  if (name === "target irr = net irr") return valuesWithin(metrics, "target_returns.target_irr", "target_returns.net_irr", 0.25);
  if (name === "equity multiple = net equity multiple") return valuesWithin(metrics, "target_returns.target_equity_multiple", "target_returns.net_equity_multiple", 0.02);
  if (name === "cash-on-cash = distribution yield") return valuesWithin(metrics, "target_returns.target_cash_on_cash", "target_returns.distribution_yield", 0.25);

  if (name.includes("dscr") || name.includes("debt service")) {
    const reported = numberValue(getPath(metrics, "underwriting_checks.dscr"));
    const noi = numberValue(getPath(metrics, "financial_projections.stabilized_noi"));
    const debt = numberValue(getPath(metrics, "deal_structure.debt_amount"));
    const rate = numberValue(getPath(metrics, "deal_structure.interest_rate"));
    if (reported === null || noi === null || debt === null || rate === null || rate <= 0) return false;
    const annualDebtService = debt * (rate / 100);
    return annualDebtService > 0 && Math.abs(noi / annualDebtService - reported) < 0.05;
  }

  if (name === "ltv = debt / total cost") {
    const reported = numberValue(getPath(metrics, "deal_structure.ltv"));
    const debt = numberValue(getPath(metrics, "deal_structure.debt_amount"));
    const total = numberValue(getPath(metrics, "deal_structure.total_project_cost"));
    return reported !== null && debt !== null && total !== null && total > 0 && Math.abs(debt / total * 100 - reported) < 0.5;
  }

  if (name === "total project cost = equity + debt" || name === "total project cost = equity + debt + pref equity") {
    const total = numberValue(getPath(metrics, "deal_structure.total_project_cost"));
    const equity = numberValue(getPath(metrics, "deal_structure.total_equity_required"));
    const debt = numberValue(getPath(metrics, "deal_structure.debt_amount"));
    const pref = numberValue(getPath(metrics, "deal_structure.preferred_equity_amount")) ?? 0;
    return total !== null && equity !== null && debt !== null && total > 0 && Math.abs(equity + debt + pref - total) / total * 100 < 1;
  }

  if (name.includes("hard") && name.includes("soft") && name.includes("land") && name.includes("contingency")) {
    const hard = costNumber(metrics, "hard_costs");
    const soft = costNumber(metrics, "soft_costs");
    const land = costNumber(metrics, "land_cost");
    const contingency = costNumber(metrics, "contingency") ?? 0;
    const total = numberValue(getPath(metrics, "deal_structure.total_project_cost"));
    return hard !== null && soft !== null && land !== null && total !== null && total > 0 && Math.abs(hard + soft + land + contingency - total) / total * 100 < 2;
  }

  return false;
}

function mathDetail(check: MathCheck, metrics: Metrics): string {
  const name = normalizeMathName(check.check ?? "");
  const fallback = [check.difference, check.formula].filter(Boolean).join(" - ");

  if (name === "target irr = net irr") {
    return aliasMathDetail(metrics, "target_returns.target_irr", "target_returns.net_irr", "%", "Target IRR must represent investor net IRR. If the document quotes cash-on-cash or distribution yield, it belongs in a separate field.") ?? fallback;
  }
  if (name === "equity multiple = net equity multiple") {
    return aliasMathDetail(metrics, "target_returns.target_equity_multiple", "target_returns.net_equity_multiple", "x", "Target equity multiple should reconcile to investor net equity multiple when both are present.") ?? fallback;
  }
  if (name === "cash-on-cash = distribution yield") {
    return aliasMathDetail(metrics, "target_returns.target_cash_on_cash", "target_returns.distribution_yield", "%", "Cash-on-cash and distribution yield should match unless the document explicitly separates scenarios.") ?? fallback;
  }

  if (name.includes("dscr") || name.includes("debt service")) {
    const reported = numberValue(getPath(metrics, "underwriting_checks.dscr"));
    const noi = numberValue(getPath(metrics, "financial_projections.stabilized_noi"));
    const debt = numberValue(getPath(metrics, "deal_structure.debt_amount"));
    const rate = numberValue(getPath(metrics, "deal_structure.interest_rate"));
    const totalCost = numberValue(getPath(metrics, "deal_structure.total_project_cost"));
    if (reported !== null && noi !== null && debt !== null && rate !== null && rate > 0) {
      const annualDebtService = debt * (rate / 100);
      if (annualDebtService > 0) {
        const calculated = noi / annualDebtService;
        const unitHint = debt > 0 && debt < 1_000_000 && (totalCost ?? 0) > 10_000_000
          ? " Debt amount looks unusually small for this deal; use full dollars or a suffix like 65.95M if the source is in millions."
          : "";
        return `${Math.abs(calculated - reported).toFixed(2)}x off after saved inputs - ${formatFormulaMoney(noi)} / ${formatFormulaMoney(annualDebtService)} = ${calculated.toFixed(2)}x.${unitHint}`;
      }
    }
  }

  if (name === "ltv = debt / total cost") {
    const reported = numberValue(getPath(metrics, "deal_structure.ltv"));
    const debt = numberValue(getPath(metrics, "deal_structure.debt_amount"));
    const total = numberValue(getPath(metrics, "deal_structure.total_project_cost"));
    if (reported !== null && debt !== null && total !== null && total > 0) {
      const calculated = debt / total * 100;
      return `${Math.abs(calculated - reported).toFixed(1)}pp off after saved inputs - ${formatFormulaMoney(debt)} / ${formatFormulaMoney(total)} = ${calculated.toFixed(1)}% LTV.`;
    }
  }

  if (name === "total project cost = equity + debt" || name === "total project cost = equity + debt + pref equity") {
    const total = numberValue(getPath(metrics, "deal_structure.total_project_cost"));
    const equity = numberValue(getPath(metrics, "deal_structure.total_equity_required"));
    const debt = numberValue(getPath(metrics, "deal_structure.debt_amount"));
    const pref = numberValue(getPath(metrics, "deal_structure.preferred_equity_amount")) ?? 0;
    if (total !== null && equity !== null && debt !== null && total > 0) {
      const sum = equity + debt + pref;
      const formula = pref > 0 ? `${formatFormulaMoney(equity)} + ${formatFormulaMoney(debt)} + ${formatFormulaMoney(pref)}` : `${formatFormulaMoney(equity)} + ${formatFormulaMoney(debt)}`;
      return `${(Math.abs(sum - total) / total * 100).toFixed(1)}% off after saved inputs - ${formula} = ${formatFormulaMoney(sum)}.`;
    }
  }

  if (name.includes("hard") && name.includes("soft") && name.includes("land") && name.includes("contingency")) {
    const hard = costNumber(metrics, "hard_costs");
    const soft = costNumber(metrics, "soft_costs");
    const land = costNumber(metrics, "land_cost");
    const contingency = costNumber(metrics, "contingency") ?? 0;
    const total = numberValue(getPath(metrics, "deal_structure.total_project_cost"));
    if (hard !== null && soft !== null && land !== null && total !== null && total > 0) {
      const sum = hard + soft + land + contingency;
      return `${(Math.abs(sum - total) / total * 100).toFixed(1)}% off after saved inputs - ${formatFormulaMoney(hard)} + ${formatFormulaMoney(soft)} + ${formatFormulaMoney(land)} + ${formatFormulaMoney(contingency)} = ${formatFormulaMoney(sum)}.`;
    }
  }

  return fallback || "A deterministic calculation does not match the current saved deal values.";
}

function findMathConfig(checkName: string): MathConfig | undefined {
  const name = normalizeMathName(checkName);
  return MATH_CONFIGS.find((config) => config.test(name));
}

function normalizeMathName(name: string): string {
  return name.toLowerCase().replace(/\s+/g, " ").trim();
}

function aliasMathDetail(metrics: Metrics, aliasPath: string, canonicalPath: string, unit: "%" | "x", note: string): string | undefined {
  const alias = numberValue(getPath(metrics, aliasPath));
  const canonical = numberValue(getPath(metrics, canonicalPath));
  if (alias === null || canonical === null) return undefined;
  return `${formatFormulaNumber(Math.abs(alias - canonical), unit)} off after saved inputs - ${aliasPath} ${formatFormulaNumber(alias, unit)} must reconcile to ${canonicalPath} ${formatFormulaNumber(canonical, unit)}. ${note}`;
}

function valuesWithin(metrics: Metrics, leftPath: string, rightPath: string, tolerance: number): boolean {
  const left = numberValue(getPath(metrics, leftPath));
  const right = numberValue(getPath(metrics, rightPath));
  return left !== null && right !== null && Math.abs(left - right) <= tolerance;
}

function costNumber(metrics: Metrics, base: "hard_costs" | "soft_costs" | "land_cost" | "contingency"): number | null {
  const totalPath = `construction_costs.${base === "land_cost" ? "land_cost_total" : `${base}_total`}`;
  return firstNumber(getPath(metrics, totalPath), getPath(metrics, `construction_costs.${base}`), getPath(metrics, `financial_projections.${base}`));
}

function reviewInputsForFlag(message: string, primaryPath: string | undefined, metrics: Metrics, provenance: Record<string, FieldProvenance>): ReviewInput[] | undefined {
  const paths = new Set<string>();
  if (primaryPath) paths.add(primaryPath);
  for (const path of message.match(/[a-z_]+\.[a-z_]+/g) ?? []) {
    if (REVIEW_FIELDS.some((field) => field.path === path)) paths.add(path);
  }
  const inputs = Array.from(paths)
    .map((path) => ({ path, label: humanizePath(path), value: getPath(metrics, path), provenance: provenance[path] }))
    .filter((input, pos, arr) => arr.findIndex((candidate) => candidate.path === input.path) === pos);
  return inputs.length > 0 ? inputs : undefined;
}

function aliasRecommendation(message: string): { path: string; value: number; label: string } | undefined {
  const canonicalMatch = message.match(/\(([a-z_]+\.[a-z_]+)\s*=\s*([0-9.]+)(%|x)?\)/);
  const allPaths = message.match(/[a-z_]+\.[a-z_]+/g) ?? [];
  if (!canonicalMatch || allPaths.length < 2) return undefined;
  const aliasPath = allPaths.find((p) => p !== canonicalMatch[1] && p.includes("target_")) ?? allPaths[1];
  const value = Number(canonicalMatch[2]);
  if (!Number.isFinite(value)) return undefined;
  return { path: aliasPath, value, label: "Apply fix" };
}

function extractBestPath(message: string): string | undefined {
  const matches = message.match(/[a-z_]+\.[a-z_]+/g) ?? [];
  return matches.find((path) => path.includes("target_")) ?? matches.find((path) => path.includes("net_")) ?? matches[0];
}

function flagTitle(flag: ValidationFlag, path?: string): string {
  if (path) return `${humanizePath(path)} needs review`;
  return `${flag.category} needs review`;
}

function simplifyMessage(message: string): string {
  if (message.length <= 190) return message;
  return `${message.slice(0, 187)}...`;
}

function sourceDetail(provenance: FieldProvenance): string {
  if (Array.isArray(provenance.conflict) && provenance.conflict.length > 1) return "Documents disagree. Pick the correct source value and lock it.";
  if (provenance.status === "wrong") return "Verification challenged this value. Confirm the correction or edit the field.";
  if (provenance.status === "missing") return "This required field is missing from the extracted data.";
  if (provenance.status === "unverifiable") return "The verifier could not tie this value back to a source document.";
  if (typeof provenance.confidence === "number") return `Confidence is ${provenance.confidence}%, below the 85% review threshold.`;
  return "This value still needs human review before it can be trusted.";
}

function sourceLabel(provenance?: FieldProvenance): string | undefined {
  if (!provenance?.source_doc_name) return undefined;
  return `${provenance.source_doc_name}${provenance.source_page ? ` p.${provenance.source_page}` : ""}`;
}

function sourceHref(provenance: FieldProvenance | undefined, path: string): string {
  if (provenance?.source_doc_id) {
    const page = provenance.source_page ? `#page=${provenance.source_page}` : "";
    return `/api/deals/documents/${provenance.source_doc_id}/file${page}`;
  }
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

function firstNumber(...values: unknown[]): number | null {
  for (const value of values) {
    const parsed = numberValue(value);
    if (parsed !== null) return parsed;
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
  if (typeof original === "number") return raw;
  return raw;
}

function formatFormulaMoney(value: number): string {
  return `$${Math.round(value).toLocaleString()}`;
}

function formatFormulaNumber(value: number, unit: "%" | "x"): string {
  if (unit === "x") return `${value.toFixed(2)}x`;
  return `${value.toFixed(2)}%`;
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
