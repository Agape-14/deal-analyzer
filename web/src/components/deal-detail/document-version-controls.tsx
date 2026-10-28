"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import type { DealDocument } from "@/lib/types";

export function DocumentVersionControls({ dealId, revision, document, documents }: {
  dealId: number; revision?: number; document: DealDocument; documents: DealDocument[];
}) {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [role, setRole] = React.useState(document.source_role ?? "active");
  const [replacement, setReplacement] = React.useState(String(document.superseded_by_id ?? ""));
  const [reason, setReason] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [editingRevision, setEditingRevision] = React.useState(revision);
  function toggle() {
    if (!open) {
      setRole(document.source_role ?? "active");
      setReplacement(String(document.superseded_by_id ?? ""));
      setReason(""); setEditingRevision(revision);
    }
    setOpen(!open);
  }
  async function save() {
    setSaving(true);
    try {
      const response = await fetch(`/api/deals/${dealId}/documents/${document.id}/version`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision: editingRevision, source_role: role,
          superseded_by_id: role === "superseded" ? Number(replacement) : null, reason }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Could not update document use.");
      toast.success("Document use updated", { description: body.message });
      setOpen(false); router.refresh();
    } catch (error) { toast.error((error as Error).message); }
    finally { setSaving(false); }
  }
  return <div className="mt-2 text-xs">
    {document.duplicate_of_id && <p className="text-muted-foreground">Identical copy of document #{document.duplicate_of_id}; counted once.</p>}
    {document.same_name_different_content && <p className="text-warning">Same filename, different contents. Check which version applies.</p>}
    {document.source_role === "superseded" && <p className="text-muted-foreground">Replaced by document #{document.superseded_by_id}; original retained.</p>}
    {document.source_role === "alternative" && <p className="text-muted-foreground">Alternate scenario; excluded from primary review.</p>}
    <button className="mt-1 text-primary underline" onClick={toggle} aria-expanded={open}>Change document use</button>
    {open && <div className="mt-2 space-y-2 rounded-md border p-3">
      <p>This choice applies to identical copies too. Keep supporting amendments active. Only mark a file replaced when the newer document replaces it in full.</p>
      <label className="block">Use for this deal
        <select className="block w-full rounded border bg-background p-2" value={role} onChange={e => setRole(e.target.value as typeof role)}>
          <option value="active">Current source / supporting amendment</option>
          <option value="alternative">Alternate scenario</option>
          <option value="superseded">Replaced in full</option>
        </select>
      </label>
      {role === "superseded" && <label className="block">Replacement document
        <select className="block w-full rounded border bg-background p-2" value={replacement} onChange={e => setReplacement(e.target.value)}>
          <option value="">Choose a current document</option>
          {documents.filter(d => (d.duplicate_of_id ?? d.id) !== (document.duplicate_of_id ?? document.id) && (!d.source_role || d.source_role === "active")).map(d => <option key={d.id} value={d.id}>{d.filename} (#{d.id})</option>)}
        </select>
      </label>}
      <label className="block">Reason
        <input className="block w-full rounded border bg-background p-2" value={reason} onChange={e => setReason(e.target.value)} maxLength={1000} />
      </label>
      <Button size="sm" onClick={save} disabled={saving || !revision || reason.trim().length < 3 || (role === "superseded" && !replacement)}>{saving ? "Saving…" : "Save document use"}</Button>
      <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
    </div>}
  </div>;
}
