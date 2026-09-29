"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { motion } from "framer-motion";
import { Building2, Loader2, Plus, UploadCloud, X, FileText } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogSheet, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useCurrentUser } from "@/lib/auth-client";
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
  const { isAnalyst, loading: authLoading } = useCurrentUser();
  const [open, setOpen] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const [developers, setDevelopers] = React.useState<Developer[] | null>(null);
  const [mode, setMode] = React.useState<"upload" | "manual">("upload");
  const [files, setFiles] = React.useState<File[]>([]);
  const [uploadError, setUploadError] = React.useState("");
  const [savedDealId, setSavedDealId] = React.useState<number | null>(null);
  const tokenRef = React.useRef<string | null>(null);
  function addFiles(incoming: File[]) {
    if (files.length + incoming.length > 10) { setUploadError("Choose up to 10 documents per deal upload."); return; }
    if (incoming.some(file => !/\.(pdf|xlsx|xlsm|xls|csv)$/i.test(file.name) || file.size === 0 || file.size > 50 * 1024 * 1024)) {
      setUploadError("Choose nonempty PDF, Excel or CSV documents, no larger than 50 MB each."); return;
    }
    setUploadError("");
    setFiles(current => [...current, ...incoming]);
  }

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
    if (authLoading) return;
    if (searchParams?.get("new") !== "1") return;
    if (isAnalyst) {
      setOpen(true);
    } else {
      router.replace("/", { scroll: false });
    }
  }, [authLoading, isAnalyst, router, searchParams]);

  React.useEffect(() => {
    function onOpen() {
      if (isAnalyst) setOpen(true);
    }
    document.addEventListener("open-new-deal", onOpen);
    return () => document.removeEventListener("open-new-deal", onOpen);
  }, [isAnalyst]);

  // Pull developers once the drawer opens (we don't need them before).
  React.useEffect(() => {
    if (!open || mode !== "manual" || developers !== null) return;
    api
      .get<Developer[]>("/api/developers")
      .then(setDevelopers)
      .catch(() => setDevelopers([]));
  }, [open, mode, developers]);

  function closeAndClear() {
    if (submitting) return;
    setOpen(false);
    setFiles([]);
    setMode("upload");
    setUploadError("");
    setSavedDealId(null);
    tokenRef.current = null;
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
    if (!isAnalyst) {
      toast.error("Viewer accounts are read-only");
      return;
    }
    if (mode === "upload") {
      if (!files.length) { toast.error("Choose at least one document"); return; }
      setSubmitting(true);
      setUploadError("");
      try {
        tokenRef.current ??= crypto.randomUUID();
        const body = new FormData();
        body.append("intake_token", tokenRef.current);
        body.append("project_name", form.project_name.trim());
        files.forEach(file => body.append("files", file));
        const response = await fetch("/document-upload/intake", { method: "POST", body });
        const result = await response.json();
        if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Upload could not be completed");
        setSavedDealId(result.deal_id);
        if (result.errors?.length) {
          const failedNames = new Set(result.errors.map((error: { filename: string }) => error.filename));
          setFiles(current => current.filter(file => failedNames.has(file.name)));
          throw new Error(result.errors.map((error: { filename: string; detail: string }) => `${error.filename}: ${error.detail}`).join(" · "));
        }
        setOpen(false);
        setFiles([]);
        tokenRef.current = null;
        toast.success("Documents saved", { description: "Your deal is ready for document review." });
        router.push(`/deals/${result.deal_id}?tab=documents`);
        router.refresh();
      } catch (err) {
        setUploadError((err as Error).message || "Upload failed. Your selected files are ready to retry.");
      } finally { setSubmitting(false); }
      return;
    }
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

      const deal = await api.post<DealSummary>("/api/deals", {
        project_name: form.project_name.trim(),
        developer_id: devId,
        city: form.city.trim(),
        state: form.state.trim(),
        property_type: form.property_type,
      });

      toast.success(`Created “${form.project_name.trim()}”`, {
        description: "Upload an offering memo to auto-populate metrics.",
      });
      setOpen(false);
      router.push(`/deals/${deal.id}?tab=documents`);
      router.refresh();
    } catch (err) {
      const detail = (err as { detail?: string })?.detail ?? "Something went wrong";
      toast.error("Couldn't create deal", { description: detail });
    } finally {
      setSubmitting(false);
    }
  }

  if (!authLoading && !isAnalyst) return null;

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
              <DialogDescription>Start with documents. Review only what needs attention.</DialogDescription>
            </div>
          </div>
        </div>

        <div className="mx-6 mt-5 grid grid-cols-2 rounded-lg bg-muted/60 p-1">
          {(["upload", "manual"] as const).map(value => <button key={value} disabled={submitting} onClick={() => setMode(value)} className={cn("rounded-md px-3 py-2 text-sm transition-colors", mode === value && "bg-background shadow-sm font-medium")}>{value === "upload" ? "Upload documents" : "Enter details"}</button>)}
        </div>
        {mode === "upload" ? <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          <div onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (!submitting) addFiles(Array.from(e.dataTransfer.files)); }} className="rounded-xl border-2 border-dashed border-primary/35 bg-primary/5 p-6 text-center">
            <UploadCloud className="mx-auto h-9 w-9 text-primary mb-3" />
            <p className="font-medium">Drop the deal documents here</p>
            <p className="mt-1 text-xs text-muted-foreground">Offering memo, financials or investor terms · PDF, Excel, CSV · up to 10 files, 50 MB each</p>
            <label className="mt-4 inline-block cursor-pointer rounded-lg border border-border bg-background px-4 py-2 text-sm font-medium">Choose documents<input aria-label="Choose deal documents" type="file" multiple accept=".pdf,.xlsx,.xlsm,.xls,.csv" disabled={submitting} className="sr-only" onChange={e => { addFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} /></label>
          </div>
          {files.length > 0 && <ul className="space-y-2">{files.map((file, index) => <li key={`${file.name}-${index}`} className="flex min-w-0 items-center gap-2 rounded-lg border border-border p-3 text-sm"><FileText className="h-4 w-4 shrink-0 text-muted-foreground" /><span className="truncate flex-1">{file.name}</span><span className="text-xs text-muted-foreground shrink-0">{(file.size / 1024 / 1024).toFixed(1)} MB</span><button type="button" aria-label={`Remove ${file.name}`} disabled={submitting} onClick={() => setFiles(current => current.filter((_, i) => i !== index))}><X className="h-4 w-4" /></button></li>)}</ul>}
          <Field label="Deal name (optional)"><Input aria-label="Deal name (optional)" value={form.project_name} maxLength={255} onChange={e => setForm(f => ({ ...f, project_name: e.target.value }))} placeholder="Use the first document name" disabled={submitting} /></Field>
          <p className="text-sm text-muted-foreground">No sponsor or location entry needed to start. Numbers remain withheld until their evidence is accepted.</p>
          {uploadError && <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm"><p>{uploadError}</p>{savedDealId && <a className="mt-2 block underline" href={`/deals/${savedDealId}?tab=documents`}>Open the documents already saved</a>}<p className="mt-2 text-xs text-muted-foreground">Retry uses this same deal and skips identical files.</p></div>}
        </form> : <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
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
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-background",
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
        </form>}

        <div className="border-t border-border/70 px-6 py-4 flex items-center justify-end gap-2 bg-background/40">
          <Button type="button" variant="ghost" onClick={closeAndClear} disabled={submitting}>
            Cancel
          </Button>
          <Button type="button" onClick={handleSubmit} disabled={submitting}>
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            {submitting ? "Saving…" : mode === "upload" ? savedDealId ? "Retry remaining documents" : "Upload and review" : "Create deal"}
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
  const id = React.useId();
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>
        {label}
        {required && <span className="text-primary ml-1">*</span>}
      </Label>
      {React.isValidElement<{ id?: string }>(children) ? React.cloneElement(children, { id }) : children}
    </div>
  );
}
