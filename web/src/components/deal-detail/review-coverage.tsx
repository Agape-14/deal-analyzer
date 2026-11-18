import Link from "next/link";
import type { ReviewCoverage, ReviewCoverageGroup } from "@/lib/types";

export const coverageLabels: Record<ReviewCoverageGroup, string> = {
  project_details: "Project details",
  construction_budget: "Construction budget",
  primary_return: "Primary return",
  scoring_inputs: "Scoring inputs",
};

const groupStates = {
  available: "Available",
  partial: "Partial coverage",
  needs_review: "Needs review",
  not_stated: "Not stated in the reviewed sources",
  not_applicable: "Not applicable",
};

const sourceStates = {
  read: "Sources read",
  partial: "Some source material could not be read",
  unread: "Some sources still need to be read",
  unknown: "Source reading has not been checked",
  no_documents: "Add the deal documents",
};

export function ReviewCoveragePanel({ coverage, dealId }: { coverage: ReviewCoverage; dealId: number }) {
  const flaggedSources = coverage.sources.documents.filter(document => document.issues.length || document.status !== "read");
  const reviewHref = `/deals/${dealId}?tab=documents${coverage.sources.status === "read" ? "#codex-review" : ""}`;
  return (
    <section aria-label="Review coverage" className="mt-4 border-t border-border/70 pt-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">Review coverage</h3>
          <p className="mt-1 text-xs text-muted-foreground">{sourceStates[coverage.sources.status]}</p>
        </div>
        {(coverage.attention_count > 0 || coverage.sources.status !== "read") && (
          <Link href={reviewHref} className="text-xs font-medium text-primary underline underline-offset-2">
            {coverage.sources.status === "read" ? "Open document review" : "Check documents"}
          </Link>
        )}
      </div>
      {flaggedSources.length > 0 && (
        <details className="mt-2 text-xs text-muted-foreground">
          <summary className="cursor-pointer">{flaggedSources.length} source{flaggedSources.length === 1 ? "" : "s"} to check</summary>
          <ul className="mt-2 space-y-1">
            {flaggedSources.map(document => <li key={document.id}>{document.filename} · {document.issues.join(" ") || sourceStates[document.status]}</li>)}
          </ul>
        </details>
      )}
      <ul className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {coverage.groups.map(group => (
          <li key={group.key} className="min-w-0 rounded-lg border border-border/70 bg-background/60 p-3 text-xs">
            <p className="font-medium">{group.label}</p>
            <p className={group.status === "partial" || group.status === "needs_review" ? "mt-1 font-medium text-warning" : "mt-1 text-muted-foreground"}>
              {groupStates[group.status]}
            </p>
            {group.action && <p className="mt-1 text-muted-foreground">{group.action}</p>}
            {group.missing.length > 0 && (group.status === "partial" || group.status === "needs_review") && (
              <p className="mt-1 text-muted-foreground">{group.missing.join(", ")}</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
