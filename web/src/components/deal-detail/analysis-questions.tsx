"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useCurrentUser } from "@/lib/auth-client";
import type { AnalysisQuestion, DealDetail } from "@/lib/types";
import { FactEvidence, factValue } from "./accepted-summary";

export function AnalysisQuestions({ deal }: { deal: DealDetail }) {
  const questions = deal.analysis?.questions ?? [];
  return <div className="space-y-5">
    <div><h2 className="text-xl font-semibold">Only the questions that affect the summary</h2><p className="mt-2 text-sm text-muted-foreground">Upload the missing evidence first; document review can resolve these automatically. Save an analyst decision only when you have checked the values yourself. Optional context and investment cautions do not create tasks here.</p></div>
    {questions.length === 0 ? <Card className="p-6">No material questions remain in this analysis. Accepted facts and their evidence are available in Summary.</Card> : questions.map(q => <QuestionCard key={`${deal.revision}-${q.id}`} question={q} deal={deal} />)}
  </div>;
}

function QuestionCard({ question, deal }: { question: AnalysisQuestion; deal: DealDetail }) {
  const router = useRouter();
  const { isAnalyst, loading } = useCurrentUser();
  const [values, setValues] = React.useState<Record<string, string>>(() => Object.fromEntries(question.issues.map(i => [i.path, String(deal.analysis?.facts[i.path]?.value ?? "")])));
  const [reason, setReason] = React.useState("");
  const [editing, setEditing] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState("");
  async function save(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true); setError("");
    try {
      await api.post(`/api/deals/${deal.id}/analysis/resolve`, { expected_revision: deal.revision, reason, fields: question.issues.map(i => ({ path: i.path, value: values[i.path] })) });
      router.refresh();
    } catch (err) {
      setError((err as { detail?: string }).detail ?? (err instanceof Error ? err.message : "The decisions could not be saved. Reload and try again."));
    } finally { setSaving(false); }
  }
  return <Card className="p-5 md:p-6"><h3 className="text-base font-semibold">{question.title}</h3><p className="mt-1 text-sm text-muted-foreground">{question.impact}</p>
    <form onSubmit={save} className="mt-4 space-y-4">
      {question.issues.map(issue => {
        const fact = deal.analysis?.facts[issue.path];
        const label = fact?.label ?? issue.path.split(".").pop()?.replaceAll("_", " ") ?? "Value";
        return <div key={issue.path} className="rounded-lg border border-border p-4"><label className="text-sm font-medium" htmlFor={`${question.id}-${issue.path}`}>{label}{fact && fact.identity.unit !== "text" ? ` (${fact.identity.unit})` : ""}</label><p className="mt-1 text-sm text-muted-foreground">{issue.reason}</p>
          {editing ? issue.path === "target_returns.primary_strategy" ? <select id={`${question.id}-${issue.path}`} value={values[issue.path]} onChange={e => setValues({ ...values, [issue.path]: e.target.value })} required className="mt-2 w-full rounded-md border bg-background p-2"><option value="">Choose strategy</option><option value="hold">Long-term hold</option><option value="sale">Sale</option><option value="hold_with_sale_option">Hold with optional sale</option></select> : <input id={`${question.id}-${issue.path}`} className="mt-2 w-full rounded-md border bg-background p-2 text-sm" required value={values[issue.path]} onChange={e => setValues({ ...values, [issue.path]: e.target.value })} /> : <p className="mt-2 text-sm">Reported: {factValue(fact, true)}</p>}
          <FactEvidence fact={fact} />
        </div>;
      })}
      {editing && <label className="block text-sm">Reason or source for your decision<textarea required minLength={3} maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} className="mt-2 min-h-20 w-full rounded-md border bg-background p-2" /><span className="mt-1 block text-xs text-muted-foreground">Saving locks these values against automatic replacement and records an analyst decision.</span></label>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <div className="flex flex-wrap items-center gap-3"><Link href={`/deals/${deal.id}?tab=documents`} className="text-sm underline">Add supporting documents</Link>
        {!loading && isAnalyst && (editing ? <><Button type="submit" disabled={saving || !deal.revision}>{saving ? "Saving…" : "Save these decisions"}</Button><Button type="button" variant="ghost" onClick={() => setEditing(false)} disabled={saving}>Cancel</Button></> : <Button type="button" variant="outline" onClick={() => setEditing(true)}>Resolve with an analyst decision</Button>)}
      </div>
    </form>
  </Card>;
}
