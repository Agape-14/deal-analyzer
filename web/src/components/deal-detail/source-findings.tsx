"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";
import { useCurrentUser } from "@/lib/auth-client";
import type { DealDetail, SourceFinding } from "@/lib/types";
import { EvidenceViewer } from "./evidence-viewer";

type FindingResolution = { revision: number; findings: SourceFinding[] };

function sourceLabel(source: SourceFinding["evidence"][number]) {
  const locator = source.page ? `page ${source.page}`
    : [source.sheet, source.cell].filter(Boolean).join(" ");
  return [source.document_name, locator].filter(Boolean).join(" · ");
}

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
  const choiceId = useId();
  const [editing, setEditing] = useState(false);
  const [choice, setChoice] = useState("");
  const [decision, setDecision] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const conflict = finding.kind === "conflict";
  const chosenSource = finding.decision?.source_index == null ? undefined : finding.evidence[finding.decision.source_index];
  const title = finding.status === "needs_review" ? "Source changed" :
    finding.decision?.action === "keep_open" ? "Still open" :
    finding.status === "resolved" ? chosenSource ? "Preferred source saved" : "Decision recorded" : conflict ? "Conflicting sources" : "Source note";
  const readyToSave = Boolean(choice);

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!readyToSave || saving) return;
    setSaving(true);
    setError("");
    try {
      const selectingSource = choice.startsWith("source:");
      const result = await api.post<FindingResolution>(`/api/deals/${dealId}/review/findings/${finding.id}/resolve`, {
        expected_revision: revision, decision,
        action: selectingSource ? "prefer_source" : choice,
        ...(selectingSource ? { source_index: Number(choice.slice("source:".length)) } : {}),
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
          <p className="font-medium">{finding.status === "needs_review" ? "Previous analyst decision" : chosenSource ?
            "Preferred source" : finding.decision.action === "keep_open" ? "Left open for follow-up" : "Analyst decision"}</p>
          {chosenSource && <p className="mt-1 text-muted-foreground">{sourceLabel(chosenSource)}</p>}
          {finding.decision.text && <p className="mt-1 whitespace-pre-wrap text-muted-foreground">{finding.decision.text}</p>}
          <p className="mt-1 text-xs text-muted-foreground">{finding.decision.by} · {finding.decision.at.slice(0, 10)}</p>
        </div>
      )}
      {finding.status === "needs_review" ? (
        <Link className="text-sm text-primary underline" href={`/deals/${dealId}?tab=documents#codex-review`}>Review the updated source</Link>
      ) : canEdit && revision && (editing ? (
        <form className="space-y-2" onSubmit={save}>
          <fieldset className="space-y-2" disabled={saving}>
            <legend className="mb-2 text-sm font-medium">{conflict ? "Choose a cited source or leave this open" : "What should happen to this note?"}</legend>
            {conflict && finding.evidence.map((source, index) => (
              <label key={index} className="flex cursor-pointer items-start gap-2 rounded-md border border-border p-2.5 text-sm">
                <input type="radio" name={choiceId} value={`source:${index}`} checked={choice === `source:${index}`}
                  onChange={event => setChoice(event.target.value)} className="mt-1 accent-primary" />
                <span className="min-w-0 break-words">
                  <span className="block font-medium">{sourceLabel(source)}</span>
                  {source.excerpt && <span className="mt-1 block text-muted-foreground">{source.excerpt}</span>}
                </span>
              </label>
            ))}
            {!conflict && <label className="flex items-center gap-2 text-sm">
              <input type="radio" name={choiceId} value="acknowledge" checked={choice === "acknowledge"}
                onChange={event => setChoice(event.target.value)} className="accent-primary" /> Acknowledge note
            </label>}
            <label className="flex items-center gap-2 text-sm">
              <input type="radio" name={choiceId} value="keep_open" checked={choice === "keep_open"}
                onChange={event => setChoice(event.target.value)} className="accent-primary" /> Leave open
            </label>
            {conflict && <p className="text-xs text-muted-foreground">This records the source to prefer. To update a deal figure, approve a checked value in <Link className="underline" href={`/deals/${dealId}?tab=documents#codex-review`}>Documents</Link>.</p>}
          </fieldset>
          <label className="block text-sm font-medium">
            Decision note (optional)
            <textarea maxLength={1000} value={decision} onChange={event => setDecision(event.target.value)}
              className="mt-1 block w-full rounded-md border border-border bg-background p-2 text-sm font-normal" />
          </label>
          {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={saving || !readyToSave}>Save decision</Button>
            <Button type="button" size="sm" variant="ghost" disabled={saving} onClick={() => setEditing(false)}>Cancel</Button>
          </div>
        </form>
      ) : (
        <Button size="sm" variant="outline" onClick={() => {
          setDecision(finding.decision?.text ?? "");
          const previous = finding.decision?.action;
          setChoice(chosenSource ? `source:${finding.decision?.source_index}`
            : previous === "keep_open" || previous === "acknowledge" ? previous : "");
          setError("");
          setEditing(true);
        }}>
          {finding.decision ? "Update decision" : conflict ? "Review choices" : "Review note"}
        </Button>
      ))}
    </Card>
  );
}
