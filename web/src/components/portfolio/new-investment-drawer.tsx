"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Wallet, Loader2, Plus } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogSheet, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { DealSummary, DealDetail, Developer, Investment } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Add Investment drawer.
 *
 * Two modes: link to an existing deal (auto-populates sponsor + projected
 * metrics) or create a free-form position. Opens via `open-new-investment`
 * custom event so it's reusable from the header, a palette action, etc.
 */
export function NewInvestmentDrawer() {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const [deals, setDeals] = React.useState<DealSummary[] | null>(null);
  const [sponsors, setSponsors] = React.useState<Developer[]>([]);
  const [sponsorsError, setSponsorsError] = React.useState(false);
  const [dealsError, setDealsError] = React.useState(false);
  const [retry, reloadDeals] = React.useReducer(n => n + 1, 0);
  const [preview, setPreview] = React.useState<DealDetail | null>(null);
  const [previewError, setPreviewError] = React.useState(false);
  const [mode, setMode] = React.useState<"deal" | "manual">("deal");
  const [editing, setEditing] = React.useState<Investment | null>(null);
  const [form, setForm] = React.useState({
    deal_id: "",
    developer_id: "",
    project_name: "",
    sponsor_name: "",
    investment_date: "",
    amount_invested: "",
    investment_class: "",
    projected_irr: "",
    projected_equity_multiple: "",
    hold_period_years: "",
    residual_value: "",
    valuation_date: "",
  });

  React.useEffect(() => {
    function onOpen() {
      setEditing(null);
      setMode("deal");
      setOpen(true);
    }
    function onEdit(event: Event) {
      const investment = (event as CustomEvent<Investment>).detail;
      setEditing(investment);
      setMode("manual");
      setForm({ deal_id: investment.deal_id?.toString() ?? "", developer_id: investment.developer_id?.toString() ?? "", project_name: investment.project_name, sponsor_name: investment.sponsor_name,
        investment_date: investment.investment_date ?? "", amount_invested: String(investment.amount_invested), investment_class: investment.investment_class ?? "",
        projected_irr: investment.projected_irr?.toString() ?? "", projected_equity_multiple: investment.projected_equity_multiple?.toString() ?? "", hold_period_years: investment.hold_period_years?.toString() ?? "", residual_value: investment.residual_value?.toString() ?? "", valuation_date: investment.valuation_date ?? "" });
      setOpen(true);
    }
    document.addEventListener("open-new-investment", onOpen);
    document.addEventListener("open-edit-investment", onEdit);
    return () => { document.removeEventListener("open-new-investment", onOpen); document.removeEventListener("open-edit-investment", onEdit); };
  }, []);

  React.useEffect(() => {
    if (!open) return;
    let active = true;
    setDealsError(false);
    setSponsorsError(false);
    api.get<Developer[]>("/api/developers").then(data => { if (active) setSponsors(data); }).catch(() => { if (active) setSponsorsError(true); });
    api
      .get<DealSummary[]>("/api/deals")
      .then(data => { if (active) { setDeals(data); if (!data.length) setMode("manual"); } })
      .catch(() => { if (active) setDealsError(true); });
    return () => { active = false; };
  }, [open, retry]);

  React.useEffect(() => {
    setPreview(null); setPreviewError(false);
    if (!open || mode !== "deal" || !form.deal_id) return;
    let active = true;
    api.get<DealDetail>(`/api/deals/${form.deal_id}`).then(data => { if (active) setPreview(data); }).catch(() => { if (active) setPreviewError(true); });
    return () => { active = false; };
  }, [open, mode, form.deal_id]);

  function closeAndClear() {
    setOpen(false);
    setTimeout(() => {
      setMode("manual");
      setForm({
        deal_id: "",
        developer_id: "",
        project_name: "",
        sponsor_name: "",
        investment_date: "",
        amount_invested: "",
        investment_class: "",
        projected_irr: "",
        projected_equity_multiple: "",
        hold_period_years: "",
        residual_value: "",
        valuation_date: "",
      });
    }, 250);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (mode === "manual" && !form.project_name.trim()) {
      toast.error("Project name is required");
      return;
    }
    if (mode === "deal" && !form.deal_id) {
      toast.error("Select a deal");
      return;
    }
    const amount = Number(form.amount_invested);
    if (!amount || amount <= 0) {
      toast.error("Amount invested must be > 0");
      return;
    }

    setSubmitting(true);
    try {
      const body: Record<string, unknown> = {
        amount_invested: amount,
      };
      if (mode === "deal") {
        body.deal_id = Number(form.deal_id);
        if (preview?.analysis) {
          body.expected_analysis_version = preview.analysis.version;
          body.expected_analysis_input_hash = preview.analysis.input_hash;
        }
      } else {
        body.project_name = form.project_name.trim();
        body.sponsor_name = form.sponsor_name.trim();
        if (!editing?.deal_id) body.developer_id = form.developer_id ? Number(form.developer_id) : null;
      }
      if (form.investment_date) body.investment_date = form.investment_date;
      if (form.investment_class) body.investment_class = form.investment_class;
      if (form.projected_irr) body.projected_irr = Number(form.projected_irr);
      if (form.projected_equity_multiple)
        body.projected_equity_multiple = Number(form.projected_equity_multiple);
      if (form.hold_period_years) body.hold_period_years = Number(form.hold_period_years);
      if (form.residual_value || form.valuation_date || editing) {
        body.residual_value = form.residual_value.trim() ? Number(form.residual_value) : null;
        body.valuation_date = form.valuation_date || null;
      }
      if (editing) {
        body.investment_class = form.investment_class.trim();
        body.investment_date = form.investment_date || null;
        for (const key of ["projected_irr", "projected_equity_multiple", "hold_period_years"] as const) body[key] = form[key].trim() ? Number(form[key]) : null;
      }

      if (editing) await api.put(`/api/investments/${editing.id}`, body);
      else await api.post("/api/investments/", body);
      toast.success(editing ? "Investment updated" : "Investment added", {
        description:
          mode === "deal"
            ? "Linked to the selected deal and its current accepted terms."
            : `${form.project_name}.`,
      });
      closeAndClear();
      router.refresh();
    } catch (err) {
      toast.error("Couldn't add investment", {
        description: (err as { detail?: string })?.detail,
      });
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
              <Wallet className="h-4 w-4 text-primary" />
            </div>
            <div>
              <DialogTitle>{editing ? "Edit investment" : "Add investment"}</DialogTitle>
              <DialogDescription>Track a position in your portfolio.</DialogDescription>
            </div>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {!editing && <div className="flex items-center gap-1 p-1 rounded-lg bg-secondary/40 border border-border/70">
            <ModeTab active={mode === "manual"} onClick={() => setMode("manual")}>
              Manual entry
            </ModeTab>
            <ModeTab active={mode === "deal"} onClick={() => setMode("deal")}>
              Link existing deal
            </ModeTab>
          </div>}
          {!editing && dealsError && <p role="alert" className="text-sm text-warning">Deals could not be refreshed. <button type="button" className="underline" onClick={reloadDeals}>Retry deals</button> or use Manual entry.</p>}
          {editing?.deal_id && <p className="text-xs text-muted-foreground">This position remains linked to its original deal. Changes here describe your own investment record.</p>}

          {mode === "manual" ? (
            <>
              <Field label="Project name" required>
                <Input
                  autoFocus
                  value={form.project_name}
                  onChange={(e) => setForm((f) => ({ ...f, project_name: e.target.value }))}
                  placeholder="e.g. Sunset Apartments"
                />
              </Field>
              <Field label="Sponsor">
                {editing?.deal_id ? <p className="text-sm">{editing.sponsor_name} · linked through the deal</p> : <select className="w-full h-9 rounded-md border bg-background px-3 text-sm" value={form.developer_id} onChange={e => setForm(f => ({ ...f, developer_id: e.target.value, sponsor_name: sponsors.find(s => String(s.id) === e.target.value)?.name ?? "" }))}><option value="">Custom / unmapped sponsor</option>{sponsors.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select>}
                {!editing?.deal_id && !form.developer_id && <Input
                  aria-label="Custom sponsor name"
                  value={form.sponsor_name}
                  onChange={(e) => setForm((f) => ({ ...f, sponsor_name: e.target.value }))}
                  placeholder="GP / sponsor"
                />}
                {sponsorsError && <p role="alert" className="text-xs text-warning">Sponsor directory could not load. Reopen to retry; custom names remain unmapped unless uniquely matched.</p>}
                <p className="text-xs text-muted-foreground">Choose a saved sponsor to retain this relationship after a rename.</p>
              </Field>
            </>
          ) : (
            <Field label="Deal" required>
              <select
                className={cn(
                  "flex h-9 w-full rounded-md border border-input bg-background/60 px-3 text-sm",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                )}
                value={form.deal_id}
                onChange={(e) => setForm((f) => ({ ...f, deal_id: e.target.value }))}
              >
                <option value="">{deals === null ? "Loading deals…" : deals.length ? "— Select deal —" : "No deals on file"}</option>
                {deals?.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.project_name} {d.developer_name ? `· ${d.developer_name}` : ""}
                  </option>
                ))}
              </select>
              <p className="text-[11px] text-muted-foreground mt-1">
                Only accepted terms from the selected analysis are copied. Your amount and date are new investor inputs.
              </p>
              {form.deal_id && <div className="rounded-lg border p-3 text-xs space-y-1">{previewError ? "Accepted terms unavailable. Retry selecting this deal before saving." : !preview ? "Loading accepted terms…" : <><p className="font-medium">Analysis revision {preview.analysis?.version ?? "unavailable"} · {preview.analysis?.investor_class ?? "unspecified class"} · {preview.analysis?.primary_strategy ?? "unspecified strategy"}</p><p>IRR: {preview.analysis?.returns.target_irr ?? "Unavailable"}{preview.analysis?.returns.target_irr != null ? "%" : ""} · Multiple: {preview.analysis?.returns.target_equity_multiple ?? "Unavailable"}{preview.analysis?.returns.target_equity_multiple != null ? "x" : ""}</p><p>{preview.analysis?.questions.length ?? 0} evidence questions. Projections are separate from realized performance.</p></>}</div>}
            </Field>
          )}

          <div className="grid grid-cols-2 gap-4">
            <Field label="Amount invested" required>
              <Input
                type="number"
                min={0}
                step={1000}
                value={form.amount_invested}
                onChange={(e) => setForm((f) => ({ ...f, amount_invested: e.target.value }))}
                placeholder="50000"
              />
            </Field>
            <Field label="Investment date">
              <Input
                type="date"
                value={form.investment_date}
                onChange={(e) => setForm((f) => ({ ...f, investment_date: e.target.value }))}
              />
            </Field>
          </div>

          {mode === "manual" && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="space-y-5"
            >
              <Field label="Class">
                <Input
                  value={form.investment_class}
                  onChange={(e) => setForm((f) => ({ ...f, investment_class: e.target.value }))}
                  placeholder="LP / Class A / Co-GP"
                />
              </Field>

              <div className="grid grid-cols-3 gap-4">
                <Field label="Proj IRR (%)">
                  <Input
                    type="number"
                    step={0.1}
                    value={form.projected_irr}
                    onChange={(e) => setForm((f) => ({ ...f, projected_irr: e.target.value }))}
                    placeholder="16"
                  />
                </Field>
                <Field label="Proj Multiple">
                  <Input
                    type="number"
                    step={0.1}
                    value={form.projected_equity_multiple}
                    onChange={(e) => setForm((f) => ({ ...f, projected_equity_multiple: e.target.value }))}
                    placeholder="1.8"
                  />
                </Field>
                <Field label="Hold (yrs)">
                  <Input
                    type="number"
                    step={0.5}
                    value={form.hold_period_years}
                    onChange={(e) => setForm((f) => ({ ...f, hold_period_years: e.target.value }))}
                    placeholder="5"
                  />
                </Field>
              </div>
            </motion.div>
          )}
          <details className="rounded-lg border border-border/70 p-3 text-sm"><summary className="cursor-pointer">Optional current valuation</summary><p className="my-3 text-xs text-muted-foreground">Use the sponsor's dated residual value for your position, excluding cash already paid out. Total-value returns require this value; cash returned is available without it. Clear both fields to remove a valuation.</p><div className="grid grid-cols-2 gap-3"><Field label="Residual value"><Input type="number" min={0} value={form.residual_value} onChange={e => setForm(f => ({ ...f, residual_value: e.target.value }))} /></Field><Field label="Valuation date"><Input type="date" value={form.valuation_date} onChange={e => setForm(f => ({ ...f, valuation_date: e.target.value }))} /></Field></div></details>
        </form>

        <div className="border-t border-border/70 px-6 py-4 flex items-center justify-end gap-2 bg-background/40">
          <Button type="button" variant="ghost" onClick={closeAndClear} disabled={submitting}>
            Cancel
          </Button>
          <Button type="button" onClick={handleSubmit} disabled={submitting || (mode === "deal" && (!preview || previewError || dealsError))}>
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            {editing ? "Save investment" : "Add investment"}
          </Button>
        </div>
      </DialogSheet>
    </Dialog>
  );
}

function ModeTab({
  active,
  onClick,
  children,
  disabled,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "relative z-10 flex-1 px-3 h-7 text-xs font-medium rounded-md transition-colors",
        active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
        disabled && "opacity-50 cursor-not-allowed",
      )}
    >
      {active && (
        <motion.span
          layoutId="new-inv-mode"
          className="absolute inset-0 rounded-md bg-card ring-1 ring-border/80 shadow-sm"
          transition={{ type: "spring", stiffness: 420, damping: 32 }}
        />
      )}
      <span className="relative">{children}</span>
    </button>
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
      {React.Children.map(children, (child, index) => index === 0 && React.isValidElement<{ id?: string }>(child) ? React.cloneElement(child, { id }) : child)}
    </div>
  );
}
