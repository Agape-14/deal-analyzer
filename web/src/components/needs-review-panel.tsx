import Link from "next/link";
import { AlertTriangle, ArrowUpRight, CheckCircle2, HelpCircle, ShieldAlert } from "lucide-react";
import { Card } from "@/components/ui/card";
import { ScoreQualityBadge } from "@/components/deal-detail/score-quality-badge";
import { cn } from "@/lib/utils";
import type { DataQualityGate, DealQualitySummary, DealSummary } from "@/lib/types";

type ReviewIssue = {
  deal: DealSummary;
  gate: DataQualityGate;
  reason: string;
  nextAction: string;
  severity: "critical" | "warning";
};

export function NeedsReviewPanel({ deals }: { deals: DealSummary[] }) {
  const issues = deals
    .map((deal): ReviewIssue | null => {
      const gate = getQualityGate(deal);
      if (!gate || gate.stage === "verified" || gate.can_score) return null;
      return {
        deal,
        gate,
        reason: issueReason(gate),
        nextAction: issueNextAction(gate),
        severity: isCritical(gate.stage) ? "critical" : "warning",
      };
    })
    .filter(Boolean) as ReviewIssue[];

  const critical = issues.filter((i) => i.severity === "critical").length;

  return (
    <Card elevated className="mb-8 p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <div className={cn("grid h-8 w-8 place-items-center rounded-lg ring-1", issues.length ? "bg-warning/15 text-warning ring-warning/30" : "bg-success/15 text-success ring-success/30")}>
              {issues.length ? <ShieldAlert className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
            </div>
            <div>
              <h2 className="text-base font-semibold tracking-tight">Needs attention</h2>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Clear these review queues before relying on a deal score or comparing alternatives.
              </p>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="rounded-full bg-destructive/15 px-2 py-1 font-medium text-destructive ring-1 ring-destructive/30">
            {critical} critical
          </span>
          <span className="rounded-full bg-muted px-2 py-1 font-medium text-muted-foreground ring-1 ring-border">
            {issues.length} total
          </span>
        </div>
      </div>

      {issues.length === 0 ? (
        <div className="mt-4 rounded-lg border border-border/70 bg-background/35 px-4 py-3 text-sm text-muted-foreground">
          No deal-level scoring exceptions right now.
        </div>
      ) : (
        <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 gap-3">
          {issues.slice(0, 6).map(({ deal, gate, reason, nextAction, severity }) => (
            <Link
              key={deal.id}
              href={`/deals/${deal.id}`}
              className="group rounded-lg border border-border/70 bg-background/35 p-4 transition-colors hover:border-border hover:bg-muted/20"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold tracking-tight">{deal.project_name}</div>
                  <div className="mt-1 truncate text-xs text-muted-foreground">{deal.developer_name || [deal.city, deal.state].filter(Boolean).join(", ")}</div>
                </div>
                <ArrowUpRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-foreground" />
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <ScoreQualityBadge gate={gate} size="sm" />
                <span className={cn("inline-flex items-center gap-1 text-xs", severity === "critical" ? "text-destructive" : "text-warning")}>
                  {severity === "critical" ? <AlertTriangle className="h-3 w-3" /> : <HelpCircle className="h-3 w-3" />}
                  {reason}
                </span>
              </div>
              <div className="mt-3 rounded-md border border-border/70 bg-card/60 px-2.5 py-2 text-xs text-muted-foreground">
                <span className="font-medium text-foreground">Next:</span> {nextAction}
              </div>
            </Link>
          ))}
        </div>
      )}
    </Card>
  );
}

function getQualityGate(deal: DealSummary): DataQualityGate | undefined {
  if (deal.scores?.data_quality) return deal.scores.data_quality;
  const quality = deal.quality;
  if (!quality) return undefined;
  if ("stage" in quality) return quality;
  return (quality as DealQualitySummary).data_quality;
}

function issueReason(gate: DataQualityGate): string {
  const summary = gate.critical_summary;
  if (gate.stage === "math_failed") return `${gate.math_summary?.fail ?? 0} number${gate.math_summary?.fail === 1 ? "" : "s"} do not tie`;
  if (gate.stage === "conflicting") return `${summary?.conflicted ?? 0} source conflict${summary?.conflicted === 1 ? "" : "s"}`;
  if (gate.stage === "insufficient_source") return `${summary?.missing ?? 0} missing support / ${summary?.bad ?? 0} need correction`;
  if (gate.stage === "needs_review") return `${summary?.unverified ?? 0} need confirmation`;
  if (gate.stage === "provisional") return "verification pending";
  return "review needed";
}

function issueNextAction(gate: DataQualityGate): string {
  if (gate.stage === "math_failed") return "Open the deal and clear the top Needs review row.";
  if (gate.stage === "conflicting") return "Confirm the correct source value or edit the extracted input.";
  if (gate.stage === "insufficient_source") return "Add support, edit the value, or confirm the row manually.";
  if (gate.stage === "needs_review") return "Inspect the cited evidence and confirm each remaining item.";
  if (gate.stage === "provisional") return "Run the full pipeline so extraction, verification, and scoring finish.";
  return "Open the deal review queue.";
}

function isCritical(stage?: string): boolean {
  return stage === "math_failed" || stage === "conflicting" || stage === "insufficient_source";
}
