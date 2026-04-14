"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Building2, Loader2, Plus, Save } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogSheet, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { Developer } from "@/lib/types";

/**
 * Add/Edit developer drawer.
 *
 * Dispatch events:
 *   `open-new-developer`                       — opens in create mode
 *   `open-edit-developer` with detail = dev    — opens in edit mode
 */
export function DeveloperDrawer() {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<Developer | null>(null);
  const [submitting, setSubmitting] = React.useState(false);
  const [form, setForm] = React.useState({
    name: "",
    contact_name: "",
    contact_email: "",
    phone: "",
    track_record: "",
    notes: "",
  });

  React.useEffect(() => {
    function onCreate() {
      setEditing(null);
      setForm({ name: "", contact_name: "", contact_email: "", phone: "", track_record: "", notes: "" });
      setOpen(true);
    }
    function onEdit(e: Event) {
      const dev = (e as CustomEvent<Developer>).detail;
      setEditing(dev);
      setForm({
        name: dev.name ?? "",
        contact_name: dev.contact_name ?? "",
        contact_email: dev.contact_email ?? "",
        phone: dev.phone ?? "",
        track_record: dev.track_record ?? "",
        notes: dev.notes ?? "",
      });
      setOpen(true);
    }
    document.addEventListener("open-new-developer", onCreate);
    document.addEventListener("open-edit-developer", onEdit);
    return () => {
      document.removeEventListener("open-new-developer", onCreate);
      document.removeEventListener("open-edit-developer", onEdit);
    };
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) {
      toast.error("Name is required");
      return;
    }
    setSubmitting(true);
    try {
      if (editing) {
        await api.put(`/api/developers/${editing.id}`, form);
        toast.success("Saved", { description: form.name });
      } else {
        await api.post("/api/developers", form);
        toast.success("Developer added", { description: form.name });
      }
      setOpen(false);
      router.refresh();
    } catch (err) {
      toast.error("Couldn't save", { description: (err as { detail?: string })?.detail });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogSheet>
        <form onSubmit={submit} className="flex flex-col h-full">
          <div className="px-6 pt-6 pb-4 border-b border-border/70">
            <div className="flex items-center gap-3">
              <div className="h-9 w-9 rounded-lg bg-primary/10 ring-1 ring-primary/30 grid place-items-center">
                <Building2 className="h-4 w-4 text-primary" />
              </div>
              <div>
                <DialogTitle>{editing ? "Edit developer" : "Add developer"}</DialogTitle>
                <DialogDescription>
                  {editing ? `Editing ${editing.name}` : "Add a sponsor to your book."}
                </DialogDescription>
              </div>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
            <div className="space-y-2">
              <Label>
                Name<span className="text-primary ml-1">*</span>
              </Label>
              <Input
                autoFocus
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="Summit Partners"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Contact</Label>
                <Input
                  value={form.contact_name}
                  onChange={(e) => setForm((f) => ({ ...f, contact_name: e.target.value }))}
                  placeholder="Jane Doe"
                />
              </div>
              <div className="space-y-2">
                <Label>Phone</Label>
                <Input
                  value={form.phone}
                  onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
                  placeholder="(555) 123-4567"
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label>Email</Label>
              <Input
                type="email"
                value={form.contact_email}
                onChange={(e) => setForm((f) => ({ ...f, contact_email: e.target.value }))}
                placeholder="jane@summit.com"
              />
            </div>
            <div className="space-y-2">
              <Label>Track record</Label>
              <textarea
                rows={4}
                value={form.track_record}
                onChange={(e) => setForm((f) => ({ ...f, track_record: e.target.value }))}
                placeholder="12 full-cycle multifamily deals, avg 19% IRR."
                className="w-full rounded-md border border-input bg-background/60 px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background transition-colors"
              />
            </div>
            <div className="space-y-2">
              <Label>Notes</Label>
              <textarea
                rows={3}
                value={form.notes}
                onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
                placeholder="Anything worth remembering about this sponsor."
                className="w-full rounded-md border border-input bg-background/60 px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background transition-colors"
              />
            </div>
          </div>

          <div className="border-t border-border/70 px-6 py-4 flex items-center justify-end gap-2 bg-background/40">
            <Button type="button" variant="ghost" onClick={() => setOpen(false)} disabled={submitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : editing ? (
                <Save className="h-4 w-4" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
              {editing ? "Save" : "Add developer"}
            </Button>
          </div>
        </form>
      </DialogSheet>
    </Dialog>
  );
}
