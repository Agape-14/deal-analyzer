"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Mail, Phone, Building2, Pencil, Trash2, GitCompareArrows, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { FadeIn } from "@/components/motion";
import { api } from "@/lib/api";
import { cn, fmtMoney, fmtMultiple, fmtPct } from "@/lib/utils";
import type { Developer, DealSummary, Investment } from "@/lib/types";

const STATUS_STYLES: Record<string, string> = {
  reviewing: "bg-muted/60 text-muted-foreground",
  interested: "bg-primary/15 text-primary ring-1 ring-primary/30",
  passed: "bg-destructive/15 text-destructive ring-1 ring-destructive/30",
  committed: "bg-success/15 text-success ring-1 ring-success/30",
  closed: "bg-chart-3/15 text-[hsl(var(--chart-3))] ring-1 ring-[hsl(var(--chart-3))/.3]",
};

/** Full developer detail view — stats, deals table, investments summary. */
export function DeveloperDetailView({
  developer,
  deals,
  investments,
}: {
  developer: Developer;
  deals: DealSummary[];
  investments: Investment[];
}) {
  const router = useRouter();
  const [deleting, setDeleting] = React.useState(false);

  // Compute aggregate stats client-side (backend doesn't expose them)
  const stats = React.useMemo(() => computeStats(deals, investments), [deals, investments]);

  async function handleDelete() {
    if (!confirm(`Delete ${developer.name}? This won't delete their deals.`)) return;
    setDeleting(true);
    try {
      await api.delete(`/api/developers/${developer.id}`);
      toast.success("Developer moved to trash", {
        description: developer.name,
        duration: 8000,
        action: {
          label: "Undo",
          onClick: async () => {
            try {
              await api.post(`/api/developers/${developer.id}/restore`);
              toast.success("Restored");
              // Jump back onto the page. `router.back()` would work if we
              // still have history; otherwise navigate to the detail.
              window.location.href = `/developers/${developer.id}`;
            } catch {
              toast.error("Restore failed");
            }
          },
        },
      });
      router.push("/developers");
      router.refresh();
    } catch (err) {
      toast.error("Couldn't delete", { description: (err as { detail?: string })?.detail });
      setDeleting(false);
    }
  }

  return (
    <div className="max-w-[1400px] mx-auto px-6 md:px-10 py-8 md:py-10">
      <FadeIn>
        <div className="mb-5">
          <Link
            href="/developers"
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            All developers
          </Link>
        </div>

        <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-6 mb-8">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-3">
              <div className="h-11 w-11 rounded-lg bg-gradient-to-br from-primary/15 to-chart-3/15 ring-1 ring-border/60 grid place-items-center shrink-0">
                <Building2 className="h-5 w-5 text-primary" />
              </div>
              <div>
                <h1 className="text-display-lg tracking-tight">{developer.name}</h1>
                {developer.contact_name && (
                  <div className="text-sm text-muted-foreground mt-0.5">{developer.contact_name}</div>
                )}
              </div>
            </div>
            {(developer.contact_email || developer.phone) && (
              <div className="mt-4 flex flex-wrap items-center gap-5 text-sm text-muted-foreground">
                {developer.contact_email && (
                  <a
                    href={`mailto:${developer.contact_email}`}
                    className="inline-flex items-center gap-1.5 hover:text-foreground transition-colors"
                  >
                    <Mail className="h-4 w-4" />
                    {developer.contact_email}
                  </a>
                )}
                {developer.phone && (
                  <a
                    href={`tel:${developer.phone}`}
                    className="inline-flex items-center gap-1.5 hover:text-foreground transition-colors"
                  >
                    <Phone className="h-4 w-4" />
                    {developer.phone}
                  </a>
                )}
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={() =>
                document.dispatchEvent(new CustomEvent("open-edit-developer", { detail: developer }))
              }
            >
              <Pencil className="h-4 w-4" />
              Edit
            </Button>
            {deals.length >= 2 && (
              <Button size="sm" variant="outline" asChild>
                <Link href={`/compare?ids=${deals.map((d) => d.id).join(",")}&preset=exec`}>
                  <GitCompareArrows className="h-4 w-4" />
                  Compare this sponsor&apos;s deals
                </Link>
              </Button>
            )}
            <Button size="sm" variant="outline" onClick={handleDelete} disabled={deleting}>
              {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              Delete
            </Button>
          </div>
        </div>
      </FadeIn>

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Active deals" value={String(stats.activeDeals)} sublabel={`${deals.length} total`} />
        <StatCard
          label="Avg target IRR"
          value={fmtPct(stats.avgIrr)}
          sublabel={`Across ${stats.irrCount} scored deal${stats.irrCount === 1 ? "" : "s"}`}
        />
        <StatCard
          label="Avg score"
          value={stats.avgScore != null ? stats.avgScore.toFixed(1) : "—"}
          sublabel="Weighted analyst composite"
        />
        <StatCard
          label="Capital invested"
          value={fmtMoney(stats.invested)}
          sublabel={`Across ${investments.length} position${investments.length === 1 ? "" : "s"}`}
          accent={investments.length > 0 ? "primary" : undefined}
        />
      </div>

      {/* Track record */}
      {developer.track_record && (
        <Card elevated className="mt-6 p-6">
          <h3 className="text-base font-semibold tracking-tight">Track record</h3>
          <p className="mt-3 text-sm leading-relaxed whitespace-pre-wrap">{developer.track_record}</p>
        </Card>
      )}

      {/* Deals table */}
      <div className="mt-8">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">Deals</h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              {deals.length === 0
                ? "No deals yet — link a new deal to this sponsor from the deal form."
                : `${deals.length} deal${deals.length === 1 ? "" : "s"} on file.`}
            </p>
          </div>
        </div>

        {deals.length === 0 ? (
          <Card elevated className="p-10 text-center text-sm text-muted-foreground">
            This sponsor doesn&apos;t have any deals yet.
          </Card>
        ) : (
          <Card elevated className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground border-b border-border/70">
                    <th className="text-left py-2.5 px-4 font-medium">Project</th>
                    <th className="text-left py-2.5 px-4 font-medium">Location</th>
                    <th className="text-left py-2.5 px-4 font-medium">Status</th>
                    <th className="text-right py-2.5 px-4 font-medium">Score</th>
                    <th className="text-right py-2.5 px-4 font-medium">Target IRR</th>
                    <th className="text-right py-2.5 px-4 font-medium">Multiple</th>
                    <th className="text-right py-2.5 px-4 font-medium">Min invest</th>
                  </tr>
                </thead>
                <tbody>
                  {deals.map((d) => (
                    <tr key={d.id} className="border-b last:border-0 border-border/40 hover:bg-muted/30 transition-colors">
                      <td className="py-3 px-4">
                        <Link href={`/deals/${d.id}`} className="font-medium hover:text-primary">
                          {d.project_name}
                        </Link>
                      </td>
                      <td className="py-3 px-4 text-muted-foreground">
                        {[d.city, d.state].filter(Boolean).join(", ") || "—"}
                      </td>
                      <td className="py-3 px-4">
                        <span
                          className={cn(
                            "text-[10px] uppercase tracking-wider rounded-full px-2 py-0.5",
                            STATUS_STYLES[d.status] ?? STATUS_STYLES.reviewing,
                          )}
                        >
                          {d.status}
                        </span>
                      </td>
                      <td className={cn("py-3 px-4 text-right tabular-nums font-semibold", scoreColor(d.overall_score))}>
                        {d.overall_score != null ? d.overall_score.toFixed(1) : "—"}
                      </td>
                      <td className="py-3 px-4 text-right tabular-nums">{fmtPct(d.target_irr)}</td>
                      <td className="py-3 px-4 text-right tabular-nums">{fmtMultiple(d.target_equity_multiple)}</td>
                      <td className="py-3 px-4 text-right tabular-nums">{fmtMoney(d.minimum_investment)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </div>

      {/* Investments */}
      {investments.length > 0 && (
        <div className="mt-8">
          <div className="mb-3">
            <h2 className="text-lg font-semibold tracking-tight">Positions with this sponsor</h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              Investments whose sponsor name matches this developer.
            </p>
          </div>
          <Card elevated className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground border-b border-border/70">
                    <th className="text-left py-2.5 px-4 font-medium">Project</th>
                    <th className="text-left py-2.5 px-4 font-medium">Status</th>
                    <th className="text-right py-2.5 px-4 font-medium">Invested</th>
                    <th className="text-right py-2.5 px-4 font-medium">Distributions</th>
                    <th className="text-right py-2.5 px-4 font-medium">Multiple</th>
                  </tr>
                </thead>
                <tbody>
                  {investments.map((inv) => {
                    const mult =
                      inv.amount_invested > 0
                        ? (inv.total_distributions + (inv.exit_amount ?? 0)) / inv.amount_invested
                        : null;
                    return (
                      <tr key={inv.id} className="border-b last:border-0 border-border/40">
                        <td className="py-3 px-4 font-medium">{inv.project_name}</td>
                        <td className="py-3 px-4">
                          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
                            {inv.status}
                          </span>
                        </td>
                        <td className="py-3 px-4 text-right tabular-nums">{fmtMoney(inv.amount_invested)}</td>
                        <td className="py-3 px-4 text-right tabular-nums">{fmtMoney(inv.total_distributions)}</td>
                        <td className="py-3 px-4 text-right tabular-nums font-semibold">
                          {mult != null ? fmtMultiple(mult) : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}

      {developer.notes && (
        <Card elevated className="mt-6 p-6">
          <h3 className="text-base font-semibold tracking-tight">Notes</h3>
          <p className="mt-3 text-sm leading-relaxed whitespace-pre-wrap">{developer.notes}</p>
        </Card>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  sublabel,
  accent,
}: {
  label: string;
  value: string;
  sublabel?: string;
  accent?: "primary" | "success";
}) {
  const valueColor = accent === "primary" ? "text-primary" : accent === "success" ? "text-success" : "text-foreground";
  return (
    <Card elevated className="p-5 relative overflow-hidden">
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-border to-transparent" />
      <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">{label}</div>
      <div className={cn("mt-3 text-2xl font-semibold tabular-nums tracking-tight", valueColor)}>{value}</div>
      {sublabel && <div className="mt-1.5 text-xs text-muted-foreground">{sublabel}</div>}
    </Card>
  );
}

function computeStats(deals: DealSummary[], investments: Investment[]) {
  const activeStatuses = new Set(["interested", "reviewing", "committed"]);
  const activeDeals = deals.filter((d) => activeStatuses.has(d.status)).length;
  const scored = deals.filter((d) => d.overall_score != null);
  const avgScore = scored.length
    ? scored.reduce((a, d) => a + (d.overall_score ?? 0), 0) / scored.length
    : null;
  const irrs = deals.map((d) => d.target_irr).filter((x): x is number => typeof x === "number");
  const avgIrr = irrs.length ? irrs.reduce((a, b) => a + b, 0) / irrs.length : null;
  const invested = investments.reduce((a, i) => a + (i.amount_invested ?? 0), 0);
  return { activeDeals, avgScore, avgIrr, irrCount: irrs.length, invested };
}

function scoreColor(v: number | null): string {
  if (v == null) return "text-muted-foreground";
  if (v >= 8) return "text-success";
  if (v >= 6) return "text-warning";
  return "text-destructive";
}
