import type { SourceFinding } from "./types";

export function sourceFindingsNeedReview(findings: readonly Pick<SourceFinding, "kind" | "status">[] = []): boolean {
  return findings.some(finding => finding.status === "needs_review" ||
    (finding.kind === "conflict" && finding.status === "current"));
}
