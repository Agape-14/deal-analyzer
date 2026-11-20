"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";
import { useCurrentUser } from "@/lib/auth-client";
import type { DealDetail, SourceFinding } from "@/lib/types";
import { EvidenceViewer } from "./evidence-viewer";

type FindingResolution = { revision: number; findings: SourceFinding[] };

export function SourceFindings({ deal }: { deal: DealDetail }) {
  const [saved, setSaved] = useState<(FindingResolution & { dealId: number })>();
  const { isAnalyst } = useCurrentUser();
  // A pending tab navigation can return an older snapshot after the save.
  const committed = saved?.dealId === deal.id && saved.revision > (deal.revision ?? 0) ? saved : undefined;
  const findings = committed?.findings ?? deal.analysis?.findings ?? [];
  const revision = committed?.revision ?? deal.revision;
  if (findings.length === 0) return null;
  return (
    <section id="source-findings" aria-label="Source findings" className="scroll-mt-20 space-y-3">
      <h3 className="text-base font-semibold">Source findings</h3>
      {findings.map(finding => (
        <FindingCard key={`${deal.revision}-${finding.id}`} finding={finding} dealId={deal.id}
          revision={revision} canEdit={isAnalyst} onSaved={result => setSaved({ ...result, dealId: deal.id })} />
      ))}
    </section>
  );
}

function FindingCard({ finding, dealId, revision, canEdit, onSaved }: {
  finding: SourceFinding;
  dealId: number;
  revision?: number;
  canEdit: boolean;
  onSaved: (result: FindingResolution) => void;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [decision, setDecision] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const title = finding.status === "needs_review" ? "Source changed" :
    finding.status === "resolved" ? "Decision recorded" : finding.kind === "conflict" ? "Conflicting sources" : "Source note";

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const result = await api.post<FindingResolution>(`/api/deals/${dealId}/review/findings/${finding.id}/resolve`, {
        expected_revision: revision, decision,
      });
      onSaved(result);
      setEditing(false);
      router.refresh();
    } catch (error) {
      const detail = (error as { detail?: unknown }).detail;
      setError(typeof detail === "string" ? detail : "The decision could not be saved. Reload and try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className="space-y-3 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-1.5">
        <h4 className="font-medium">{finding.title}</h4>
        <span className={finding.status === "needs_review" || finding.kind === "conflict" && finding.status === "current" ? "text-xs text-warning" : "text-xs text-muted-foreground"}>{title}</span>
      </div>
      <p className="text-sm text-muted-foreground">{finding.detail}</p>
      <div className="flex flex-wrap gap-2">
        {finding.evidence.map((source, index) => (
          <EvidenceViewer key={`${source.document_id}-${source.page}-${index}`} source={source} />
        ))}
      </div>
      {finding.decision && (
        <div className="border-t border-border/70 pt-2 text-sm">
          <p className="font-medium">{finding.status === "needs_review" ? "Previous analyst decision" : "Analyst decision"}</p>
          <p className="mt-1 whitespace-pre-wrap text-muted-foreground">{finding.decision.text}</p>
          <p className="mt-1 text-xs text-muted-foreground">{finding.decision.by} · {finding.decision.at.slice(0, 10)}</p>
        </div>
      )}
      {finding.status === "needs_review" ? (
        <Link className="text-sm text-primary underline" href={`/deals/${dealId}?tab=documents#codex-review`}>Review the updated source</Link>
      ) : canEdit && revision && (editing ? (
        <form className="space-y-2" onSubmit={save}>
          <label className="block text-sm font-medium">
            Decision and basis
            <textarea required minLength={3} maxLength={1000} value={decision} onChange={event => setDecision(event.target.value)}
              className="mt-1 block w-full rounded-md border border-border bg-background p-2 text-sm font-normal" />
          </label>
          {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={saving}>Save decision</Button>
            <Button type="button" size="sm" variant="ghost" disabled={saving} onClick={() => setEditing(false)}>Cancel</Button>
          </div>
        </form>
      ) : (
        <Button size="sm" variant="outline" onClick={() => {
          setDecision(finding.decision?.text ?? "");
          setError("");
          setEditing(true);
        }}>
          {finding.decision ? "Update decision" : "Record decision"}
        </Button>
      ))}
    </Card>
  );
}
