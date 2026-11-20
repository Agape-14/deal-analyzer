"use client";
import * as React from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useCurrentUser } from "@/lib/auth-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { DealDetail, Developer } from "@/lib/types";

export function DealDetails({ deal }: { deal: DealDetail }) {
  const { isAnalyst } = useCurrentUser();
  const [developers, setDevelopers] = React.useState<Developer[]>([]);
  const [saving, setSaving] = React.useState(false);
  const [form, setForm] = React.useState({ project_name: deal.project_name, city: deal.city ?? "", state: deal.state ?? "", location: deal.location ?? "", property_type: deal.property_type, status: deal.status, notes: deal.notes ?? "", developer_id: deal.developer_id?.toString() ?? "" });
  const id = React.useId();
  React.useEffect(() => { if (isAnalyst) api.get<Developer[]>("/api/developers").then(setDevelopers).catch(() => {}); }, [isAnalyst]);
  if (!isAnalyst) return null;
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!form.project_name.trim()) return;
    setSaving(true);
    try {
      await api.put(`/api/deals/${deal.id}`, { ...form, project_name: form.project_name.trim(), developer_id: form.developer_id ? Number(form.developer_id) : null, expected_revision: deal.revision });
      window.location.reload();
    } catch (error) { toast.error("Couldn't save deal details", { description: (error as { detail?: string }).detail }); setSaving(false); }
  }
  const selectClass = "h-9 w-full rounded-md border border-input bg-background px-3 text-sm";
  return <details className="rounded-xl border border-border bg-card p-4 mb-5">
    <summary className="cursor-pointer font-medium text-sm">Edit deal details</summary>
    <form onSubmit={save} className="mt-4 space-y-4">
      <p className="text-xs text-muted-foreground">Correct document labels, set your decision status and keep notes here. Financial evidence is reviewed in Questions.</p>
      <div className="grid gap-4 sm:grid-cols-2">
        {(["project_name", "city", "state", "location"] as const).map(key => <div key={key} className="space-y-1.5"><label className="text-xs text-muted-foreground" htmlFor={`${id}-${key}`}>{key === "project_name" ? "Deal name" : key[0].toUpperCase() + key.slice(1)}</label><Input id={`${id}-${key}`} value={form[key]} maxLength={key === "project_name" ? 255 : key === "state" ? 64 : key === "city" ? 120 : 500} required={key === "project_name"} onChange={event => setForm(current => ({ ...current, [key]: event.target.value }))} /></div>)}
        <div className="space-y-1.5"><label className="text-xs text-muted-foreground" htmlFor={`${id}-sponsor`}>Sponsor</label><select id={`${id}-sponsor`} className={selectClass} value={form.developer_id} onChange={event => setForm(current => ({ ...current, developer_id: event.target.value }))}><option value="">Unspecified</option>{developers.map(developer => <option key={developer.id} value={developer.id}>{developer.name}</option>)}</select></div>
        <div className="space-y-1.5"><label className="text-xs text-muted-foreground" htmlFor={`${id}-type`}>Property type</label><select id={`${id}-type`} className={selectClass} value={form.property_type} onChange={event => setForm(current => ({ ...current, property_type: event.target.value }))}>{["multifamily", "mixed-use", "office", "retail", "industrial", "hospitality", "land", "other"].map(value => <option key={value} value={value}>{value}</option>)}</select></div>
        <div className="space-y-1.5"><label className="text-xs text-muted-foreground" htmlFor={`${id}-status`}>Decision status</label><select id={`${id}-status`} className={selectClass} value={form.status} onChange={event => setForm(current => ({ ...current, status: event.target.value as DealDetail["status"] }))}>{["reviewing", "interested", "passed", "committed", "closed"].map(value => <option key={value} value={value}>{value}</option>)}</select></div>
      </div>
      <div className="space-y-1.5"><label className="text-xs text-muted-foreground" htmlFor={`${id}-notes`}>Deal notes</label><textarea id={`${id}-notes`} className={`${selectClass} h-24 py-2`} maxLength={10000} value={form.notes} onChange={event => setForm(current => ({ ...current, notes: event.target.value }))} /></div>
      <Button type="submit" disabled={saving || !form.project_name.trim()}>{saving ? "Saving…" : "Save deal details"}</Button>
    </form>
  </details>;
}
