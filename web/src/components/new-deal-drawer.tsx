"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { motion } from "framer-motion";
import { Building2, Loader2, Plus } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogSheet, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { Developer, DealSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Side-drawer form for creating a new deal.
 *
 * Opens via:
 *   - the "New Deal" button in the header (dispatches `open-new-deal`)
 *   - the command-palette "New deal" action (which pushes `?new=1`)
 *
 * Creates the deal, shows a toast, and refreshes the server component so
 * the new deal shows up in the grid.
 */
export function NewDealDrawer() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [open, setOpen] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const [developers, setDevelopers] = React.useState<Developer[] | null>(null);

  const [form, setForm] = React.useState({
    project_name: "",
    developer_id: "",
    new_developer_name: "",
    city: "",
    state: "",
    property_type: "multifamily",
  });

  // Read ?new=1 (from command palette) and respond to a custom event (from
  // the header button). Both open the drawer the same way.
  React.useEffect(() => {
    if (searchParams?.get("new") === "1") setOpen(true);
  }, [searchParams]);

  React.useEffect(() => {
    function onOpen() {
      setOpen(true);
    }
    document.addEventListener("open-new-deal", onOpen);
    return () => document.removeEventListener("open-new-deal", onOpen);
  }, []);

  // Pull developers once the drawer opens (we don't need them before).
  React.useEffect(() => {
    if (!open || developers !== null) return;
    api
      .get<Developer[]>("/api/developers")
      .then(setDevelopers)
      .catch(() => setDevelopers([]));
  }, [open, developers]);

  function closeAndClear() {
    setOpen(false);
    // reset after the close animation so we don't flash an empty form
    setTimeout(() => {
      setForm({
        project_name: "",
        developer_id: "",
        new_developer_name: "",
        city: "",
        state: "",
        property_type: "multifamily",
      });
    }, 250);
    // clear ?new=1 from URL if present
    if (searchParams?.get("new")) {
      router.replace("/", { scroll: false });
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.project_name.trim()) {
      toast.error("Project name is required");
      return;
    }
    setSubmitting(true);
    try {
      let devId = form.developer_id ? Number(form.developer_id) : null;

      // Inline "add new developer" flow
      if (!devId && form.new_developer_name.trim()) {
        const dev = await api.post<Developer>("/api/developers", {
          name: form.new_developer_name.trim(),
        });
        devId = dev.id;
      }

      await api.post<DealSummary>("/api/deals", {
        project_name: form.project_name.trim(),
        developer_id: devId,
        city: form.city.trim(),
        state: form.state.trim(),
        property_type: form.property_type,
      });

      toast.success(`Created “${form.project_name.trim()}”`, {
        description: "Upload an offering memo to auto-populate metrics.",
      });
      closeAndClear();
      router.refresh(); // re-fetch server component
    } catch (err) {
      const detail = (err as { detail?: string })?.detail ?? "Something went wrong";
      toast.error("Couldn't create deal", { description: detail });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => (o ? setOpen(true) : closeAndClear())}>
      <DialogSheet>
        <div className="px-6 pt-6 pb-4 border-b border-border/70">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-lg bg-primary/10 ring-1 ring-primary/30 grid place-items-center">
              <Building2 className="h-4 w-4 text-primary" />
            </div>
            <div>
              <DialogTitle>New deal</DialogTitle>
              <DialogDescription>Create a deal shell, then upload an OM to score it.</DialogDescription>
            </div>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          <Field label="Project name" required>
            <Input
              autoFocus
              value={form.project_name}
              onChange={(e) => setForm((f) => ({ ...f, project_name: e.target.value }))}
              placeholder="Sunset Apartments"
            />
          </Field>

          <Field label="Developer">
            <select
              className={cn(
                "flex h-9 w-full rounded-md border border-input bg-background/60 px-3 text-sm",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                "transition-colors",
              )}
              value={form.developer_id}
              onChange={(e) => setForm((f) => ({ ...f, developer_id: e.target.value, new_developer_name: "" }))}
            >
              <option value="">— Select or add new —</option>
              {developers?.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </Field>

          {!form.developer_id && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.18 }}
            >
              <Field label="…or create a developer">
                <Input
                  value={form.new_developer_name}
                  onChange={(e) => setForm((f) => ({ ...f, new_developer_name: e.target.value }))}
                  placeholder="New sponsor name (optional)"
                />
              </Field>
            </motion.div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <Field label="City">
              <Input
                value={form.city}
                onChange={(e) => setForm((f) => ({ ...f, city: e.target.value }))}
                placeholder="Austin"
              />
            </Field>
            <Field label="State">
              <Input
                value={form.state}
                onChange={(e) => setForm((f) => ({ ...f, state: e.target.value }))}
                placeholder="TX"
                maxLength={2}
                className="uppercase"
              />
            </Field>
          </div>

          <Field label="Property type">
            <select
              className={cn(
                "flex h-9 w-full rounded-md border border-input bg-background/60 px-3 text-sm",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
              )}
              value={form.property_type}
              onChange={(e) => setForm((f) => ({ ...f, property_type: e.target.value }))}
            >
              <option value="multifamily">Multifamily</option>
              <option value="mixed-use">Mixed-use</option>
              <option value="office">Office</option>
              <option value="retail">Retail</option>
              <option value="industrial">Industrial</option>
              <option value="hospitality">Hospitality</option>
              <option value="land">Land</option>
              <option value="other">Other</option>
            </select>
          </Field>
        </form>

        <div className="border-t border-border/70 px-6 py-4 flex items-center justify-end gap-2 bg-background/40">
          <Button type="button" variant="ghost" onClick={closeAndClear} disabled={submitting}>
            Cancel
          </Button>
          <Button type="button" onClick={handleSubmit} disabled={submitting}>
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Create deal
          </Button>
        </div>
      </DialogSheet>
    </Dialog>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <Label>
        {label}
        {required && <span className="text-primary ml-1">*</span>}
      </Label>
      {children}
    </div>
  );
}
