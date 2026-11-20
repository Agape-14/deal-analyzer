"use client";

import Link from "next/link";
import { ArrowUpRight, ShieldAlert } from "lucide-react";
import { Card } from "@/components/ui/card";
import { useCurrentUser } from "@/lib/auth-client";
import { cn } from "@/lib/utils";
import type { DataQualityGate, DealSummary } from "@/lib/types";

const PRIORITY_LABELS = ["Check first", "Needs evidence", "Read sources"] as const;

type ReviewItem = {
  id: string;
  label: string;
  detail: string;
  destination: "questions" | "questions#source-findings" | "documents" | `documents#document-${number}` | "overview#return-crosscheck";
  priority: 0 | 1 | 2;
};

type DealReview = {
  deal: DealSummary;
  items: ReviewItem[];
};

function reviewItems(deal: DealSummary): ReviewItem[] {
  const { analysis } = deal;
  if (!analysis) {
    const gate = getQualityGate(deal);
    if (!gate || gate.stage === "verified" || gate.can_score) return [];
    return [{
      id: "legacy",
      label: "Deal review",
      detail: issueReason(gate),
      destination: "questions",
      priority: isCritical(gate.stage) ? 0 : 1,
    }];
  }

  const items: ReviewItem[] = [];
  const questions = analysis.questions;
  const questionPaths = new Set(questions.flatMap(question => question.issues.map(issue => issue.path)));
  if (questions.length > 0) {
    items.push({
      id: "field-questions",
      label: questions.length === 1 ? "Field questions" : `${questions.length} groups of field questions`,
      detail: questions.map(question => question.area).join(", "),
      destination: "questions",
      priority: questions.some(question => question.issues.some(issue => issue.state === "disputed")) ? 0 : 1,
    });
  }

  for (const check of analysis.readiness?.checks ?? []) {
    if (check.status !== "incomplete" && check.status !== "attention") continue;
    if (check.key === "sources") {
      const flagged = analysis.review_coverage?.sources.documents.filter(document => document.status !== "read") ?? [];
      const sourceNames = flagged.slice(0, 2).map(document => document.filename).filter(Boolean).join(", ");
      const remaining = flagged.length > 2 ? ` and ${flagged.length - 2} more` : "";
      items.push({
        id: check.key,
        label: check.label,
        detail: sourceNames ? `${sourceNames}${remaining}. ${check.detail}` : check.detail,
        destination: flagged.length === 1 ? `documents#document-${flagged[0].id}` : "documents",
        priority: 2,
      });
      continue;
    }

    // A field question already supplies the action when it covers all missing inputs.
    if (check.status === "incomplete" && (
      (check.paths.length > 0 && check.paths.every(path => questionPaths.has(path)))
      || (check.key === "returns" && check.paths.length === 0 && questions.some(question => question.area === "Returns"))
    )) continue;
    items.push({
      id: check.key,
      label: check.label,
      detail: check.detail,
      destination: "questions",
      priority: check.status === "attention" ? 0 : 1,
    });
  }

  for (const finding of analysis.findings ?? []) {
    if (finding.status !== "needs_review" && (finding.kind !== "conflict" || finding.status === "resolved")) continue;
    items.push({
      id: `finding-${finding.id}`,
      label: finding.title,
      detail: finding.detail,
      destination: "questions#source-findings",
      priority: finding.kind === "conflict" ? 0 : 1,
    });
  }

  if (analysis.return_crosscheck?.status === "needs_review") {
    items.push({
      id: "return-crosscheck",
      label: "Return cross-check",
      detail: "Recheck the cash flows against the current source documents.",
      destination: "overview#return-crosscheck",
      priority: 1,
    });
  }

  return items.sort((first, second) => first.priority - second.priority);
}

function ReviewDeals({ reviews }: { reviews: DealReview[] }) {
  return (
    <ul className="divide-y divide-border/60">
      {reviews.map(({ deal, items }) => (
        <li key={deal.id} className="grid gap-2 py-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.8fr)]">
          <div>
            <Link href={`/deals/${deal.id}`} className="break-words text-sm font-semibold hover:underline">
              {deal.project_name}
            </Link>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {deal.developer_name || [deal.city, deal.state].filter(Boolean).join(", ")}
            </p>
          </div>
          <ul className="space-y-1">
            {items.map(item => (
              <li key={item.id}>
                <Link
                  href={`/deals/${deal.id}?tab=${item.destination}`}
                  className="group block rounded-md px-2 py-1.5 text-xs focus-visible:outline focus-visible:outline-2 hover:bg-muted/40"
                >
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                    <span className={cn("font-medium", item.priority === 0 ? "text-destructive"
                      : item.priority === 1 ? "text-warning" : "text-muted-foreground")}>
                      {PRIORITY_LABELS[item.priority]}
                    </span>
                    <span className="font-medium group-hover:underline">{item.label}</span>
                    <ArrowUpRight aria-hidden="true" className="ml-auto h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  </div>
                  <p className="mt-0.5 line-clamp-2 break-words text-muted-foreground">{item.detail}</p>
                </Link>
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}

export function NeedsReviewPanel({ deals }: { deals: DealSummary[] }) {
  const { isAnalyst, loading } = useCurrentUser();
  if (loading || !isAnalyst) return null;

  const reviews = deals.map(deal => ({ deal, items: reviewItems(deal) }))
    .filter(review => review.items.length > 0)
    .sort((first, second) => first.items[0].priority - second.items[0].priority);
  if (reviews.length === 0) return null;

  return (
    <Card elevated className="relative z-0 mb-6 p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-warning/15 text-warning">
          <ShieldAlert aria-hidden="true" className="h-4 w-4" />
        </div>
        <h2 className="text-base font-semibold tracking-tight">Needs attention</h2>
        <span className="ml-auto text-xs text-muted-foreground">
          {reviews.length} {reviews.length === 1 ? "deal" : "deals"}
        </span>
      </div>
      <ReviewDeals reviews={reviews.slice(0, 6)} />
      {reviews.length > 6 && (
        <details className="border-t border-border/60 pt-3">
          <summary className="cursor-pointer text-sm font-medium">
            {reviews.length - 6} more {reviews.length === 7 ? "deal" : "deals"}
          </summary>
          <ReviewDeals reviews={reviews.slice(6)} />
        </details>
      )}
    </Card>
  );
}

function getQualityGate(deal: DealSummary): DataQualityGate | undefined {
  if (deal.scores?.data_quality) return deal.scores.data_quality;
  const quality = deal.quality;
  return quality && ("stage" in quality ? quality : quality.data_quality);
}

function issueReason(gate: DataQualityGate): string {
  const summary = gate.critical_summary;
  if (gate.stage === "math_failed") {
    const count = gate.math_summary?.fail ?? 0;
    return `${count} number${count === 1 ? " does" : "s do"} not tie`;
  }
  if (gate.stage === "conflicting") return `${summary?.conflicted ?? 0} source conflict${summary?.conflicted === 1 ? "" : "s"}`;
  if (gate.stage === "insufficient_source") return "Some values need more source support.";
  if (gate.stage === "needs_review") return "Some values still need confirmation.";
  if (gate.stage === "provisional") return "Verification is pending.";
  return "Open the deal review queue.";
}

function isCritical(stage?: string): boolean {
  return stage === "math_failed" || stage === "conflicting" || stage === "insufficient_source";
}
