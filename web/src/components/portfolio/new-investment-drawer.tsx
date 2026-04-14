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
import type { DealSummary } from "@/lib/types";
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
  const [mode, setMode] = React.useState<"deal" | "manual">("manual");
  const [form, setForm] = React.useState({
    deal_id: "",
    project_name: "",
    sponsor_name: "",
    investment_date: "",
    amount_invested: "",
    investment_class: "",
    projected_irr: "",
    projected_equity_multiple: "",
    hold_period_years: "",
  });

  React.useEffect(() => {
    function onOpen() {
      setOpen(true);
    }
    document.addEventListener("open-new-investment", onOpen);
    return () => document.removeEventListener("open-new-investment", onOpen);
  }, []);

  React.useEffect(() => {
    if (!open || deals !== null) return;
    api
      .get<DealSummary[]>("/api/deals")
      .then(setDeals)
      .catch(() => setDeals([]));
  }, [open, deals]);

  function closeAndClear() {
    setOpen(false);
    setTimeout(() => {
      setMode("manual");
      setForm({
        deal_id: "",
        project_name: "",
        sponsor_name: "",
        investment_date: "",
        amount_invested: "",
        investment_class: "",
        projected_irr: "",
        projected_equity_multiple: "",
        hold_period_years: "",
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
      } else {
        body.project_name = form.project_name.trim();
        body.sponsor_name = form.sponsor_name.trim();
      }
      if (form.investment_date) body.investment_date = form.investment_date;
      if (form.investment_class) body.investment_class = form.investment_class;
      if (form.projected_irr) body.projected_irr = Number(form.projected_irr);
      if (form.projected_equity_multiple)
        body.projected_equity_multiple = Number(form.projected_equity_multiple);
      if (form.hold_period_years) body.hold_period_years = Number(form.hold_period_years);

      await api.post("/api/investments/", body);
      toast.success("Investment added", {
        description:
          mode === "deal"
            ? "Linked to the selected deal. Metrics auto-populated."
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
              <DialogTitle>Add investment</DialogTitle>
              <DialogDescription>Track a position in your portfolio.</DialogDescription>
            </div>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          <div className="flex items-center gap-1 p-1 rounded-lg bg-secondary/40 border border-border/70">
            <ModeTab active={mode === "manual"} onClick={() => setMode("manual")}>
              Manual entry
            </ModeTab>
            <ModeTab active={mode === "deal"} onClick={() => setMode("deal")} disabled={!deals?.length}>
              Link existing deal
            </ModeTab>
          </div>

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
                <Input
                  value={form.sponsor_name}
                  onChange={(e) => setForm((f) => ({ ...f, sponsor_name: e.target.value }))}
                  placeholder="GP / sponsor"
                />
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
                <option value="">— Select deal —</option>
                {deals?.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.project_name} {d.developer_name ? `· ${d.developer_name}` : ""}
                  </option>
                ))}
              </select>
              <p className="text-[11px] text-muted-foreground mt-1">
                Will auto-populate sponsor, projected IRR/multiple, preferred return, hold period.
              </p>
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
        </form>

        <div className="border-t border-border/70 px-6 py-4 flex items-center justify-end gap-2 bg-background/40">
          <Button type="button" variant="ghost" onClick={closeAndClear} disabled={submitting}>
            Cancel
          </Button>
          <Button type="button" onClick={handleSubmit} disabled={submitting}>
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Add investment
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
