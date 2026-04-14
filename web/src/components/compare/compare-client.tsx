"use client";

import * as React from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { Loader2, Plus, FileSpreadsheet, AlertCircle, GitCompareArrows } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";
import type { DealDetail, DealSummary } from "@/lib/types";
import { PRESETS, getRow, type MetricRow } from "./presets";
import { CompareToolbar } from "./toolbar";
import { DealPicker } from "./deal-picker";
import { DealHeaderRow } from "./deal-header-row";
import { MetricsTable, type CompareMode } from "./metrics-table";
import { CustomPresetDrawer, readCustomPreset } from "./custom-preset-drawer";

const VALID_MODES: CompareMode[] = ["values", "winners", "deltas", "normalized"];

/**
 * Compare tool. State flows URL → component:
 *   ?ids=1,2,3       — selected deals
 *   ?preset=exec     — preset key (or "custom" for user's saved rows)
 *   ?mode=winners    — view mode (values / winners / deltas / normalized)
 *   ?baseline=1      — baseline deal for delta mode
 *
 * Fetching the detailed compare data uses /api/deals/compare which returns
 * full DealDetail objects (metrics + scores). We keep a tiny in-memory cache
 * keyed by the comma-sorted id list so flipping between presets is instant.
 */
export function CompareClient({ deals }: { deals: DealSummary[] }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const idsParam = searchParams?.get("ids") ?? "";
  const selectedIds = React.useMemo(
    () =>
      idsParam
        .split(",")
        .map((x) => Number(x))
        .filter((x) => Number.isFinite(x) && x > 0),
    [idsParam],
  );
  const preset = searchParams?.get("preset") ?? "exec";
  const mode = (searchParams?.get("mode") as CompareMode) ?? "winners";
  const baselineParam = searchParams?.get("baseline");
  const baselineId = baselineParam ? Number(baselineParam) : null;

  const [customKeys, setCustomKeys] = React.useState<string[]>([]);
  const [customOpen, setCustomOpen] = React.useState(false);
  const [pickerOpen, setPickerOpen] = React.useState(false);
  const [details, setDetails] = React.useState<DealDetail[] | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [overallWins, setOverallWins] = React.useState<Record<number, number>>({});

  const cacheRef = React.useRef(new Map<string, DealDetail[]>());

  // Load custom preset once on mount
  React.useEffect(() => {
    const c = readCustomPreset();
    if (c) setCustomKeys(c);
  }, []);

  // Fetch detailed compare whenever the selected-ids set changes
  React.useEffect(() => {
    if (selectedIds.length < 2) {
      setDetails(null);
      return;
    }
    const key = [...selectedIds].sort((a, b) => a - b).join(",");
    const cached = cacheRef.current.get(key);
    if (cached) {
      // Re-order to match the ids in the URL (user-visible order)
      setDetails(reorder(cached, selectedIds));
      return;
    }
    setLoading(true);
    setError(null);
    api
      .post<{ deals: DealDetail[] }>("/api/deals/compare", { deal_ids: selectedIds })
      .then((res) => {
        cacheRef.current.set(key, res.deals);
        setDetails(reorder(res.deals, selectedIds));
      })
      .catch((e) => {
        setError((e as { detail?: string })?.detail ?? "Couldn't load compare data");
      })
      .finally(() => setLoading(false));
  }, [idsParam]); // eslint-disable-line react-hooks/exhaustive-deps

  const rows: MetricRow[] = React.useMemo(() => {
    if (preset === "custom") {
      return customKeys.map((k) => getRow(k)).filter((r): r is MetricRow => Boolean(r));
    }
    return PRESETS.find((p) => p.key === preset)?.rows ?? PRESETS[0].rows;
  }, [preset, customKeys]);

  function setParams(update: Record<string, string | null>) {
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    for (const [k, v] of Object.entries(update)) {
      if (v === null || v === "") params.delete(k);
      else params.set(k, v);
    }
    const query = params.toString();
    router.replace(`${pathname}${query ? `?${query}` : ""}`, { scroll: false });
  }

  function applyPicker(ids: number[]) {
    setParams({ ids: ids.length ? ids.join(",") : null });
  }

  function removeDeal(id: number) {
    const next = selectedIds.filter((x) => x !== id);
    setParams({
      ids: next.length ? next.join(",") : null,
      baseline: baselineId === id ? null : baselineParam ?? null,
    });
  }

  function exportExcel() {
    if (selectedIds.length < 2) return;
    // Open in new tab so the browser handles the download. Backend endpoint
    // streams an .xlsx with color-coded best/worst per metric.
    fetch("/api/deals/compare/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ deal_ids: selectedIds }),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `compare-${selectedIds.join("-")}.xlsx`;
        a.click();
        URL.revokeObjectURL(url);
      })
      .catch((e) => toast.error("Export failed", { description: (e as Error).message }));
  }

  const cols = selectedIds.length;
  const modeValid = VALID_MODES.includes(mode);

  // Empty state: nothing picked yet
  if (selectedIds.length === 0) {
    return (
      <>
        <EmptyState onPick={() => setPickerOpen(true)} />
        <DealPicker
          open={pickerOpen}
          onOpenChange={setPickerOpen}
          deals={deals}
          selected={selectedIds}
          onApply={applyPicker}
        />
      </>
    );
  }

  // One deal: prompt for another
  if (selectedIds.length === 1) {
    return (
      <>
        <OneDealState dealName={deals.find((d) => d.id === selectedIds[0])?.project_name ?? "Deal"} onPick={() => setPickerOpen(true)} />
        <DealPicker
          open={pickerOpen}
          onOpenChange={setPickerOpen}
          deals={deals}
          selected={selectedIds}
          onApply={applyPicker}
        />
      </>
    );
  }

  return (
    <div>
      {/* Toolbar */}
      <div className="mb-5">
        <CompareToolbar
          preset={preset}
          onPreset={(k) => setParams({ preset: k === "exec" ? null : k })}
          mode={modeValid ? mode : "winners"}
          onMode={(m) => {
            setParams({ mode: m === "winners" ? null : m, baseline: m === "deltas" ? String(baselineId ?? selectedIds[0]) : null });
          }}
          baseline={baselineId ?? selectedIds[0]}
          onBaseline={(id) => setParams({ baseline: id ? String(id) : null })}
          deals={details ?? []}
          hasCustom={customKeys.length > 0}
          onOpenCustom={() => setCustomOpen(true)}
        />
      </div>

      {/* Actions bar — add deal + export */}
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <Button size="sm" variant="secondary" onClick={() => setPickerOpen(true)}>
            <Plus className="h-4 w-4" />
            Change selection
          </Button>
          <Button size="sm" variant="outline" onClick={exportExcel}>
            <FileSpreadsheet className="h-4 w-4" />
            Export Excel
          </Button>
        </div>
        <span className="text-xs text-muted-foreground">
          {selectedIds.length} deal{selectedIds.length === 1 ? "" : "s"} · {rows.length} metrics
        </span>
      </div>

      {loading && (
        <Card elevated className="p-10 flex items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading comparison…
        </Card>
      )}

      {error && (
        <Card elevated className="p-8 text-center">
          <AlertCircle className="h-5 w-5 text-destructive mx-auto mb-2" />
          <div className="text-sm font-medium text-destructive">Couldn&apos;t load comparison</div>
          <div className="text-xs text-muted-foreground mt-1">{error}</div>
        </Card>
      )}

      {details && !loading && (
        <>
          <DealHeaderRow deals={details} overallWins={overallWins} onRemove={removeDeal} cols={cols} />
          {rows.length === 0 ? (
            <Card elevated className="p-10 text-center text-sm text-muted-foreground">
              No metrics selected. Build your own preset or pick a preset above.
            </Card>
          ) : (
            <MetricsTable
              deals={details}
              rows={rows}
              mode={modeValid ? mode : "winners"}
              baselineId={mode === "deltas" ? baselineId ?? selectedIds[0] : null}
              onWins={setOverallWins}
              cols={cols}
            />
          )}
        </>
      )}

      <DealPicker
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        deals={deals}
        selected={selectedIds}
        onApply={applyPicker}
      />
      <CustomPresetDrawer
        open={customOpen}
        onOpenChange={setCustomOpen}
        initialKeys={customKeys.length ? customKeys : PRESETS[0].rows.map((r) => r.key)}
        onApply={(keys) => {
          setCustomKeys(keys);
          setParams({ preset: "custom" });
        }}
      />
    </div>
  );
}

function reorder(items: DealDetail[], ids: number[]): DealDetail[] {
  const map = new Map(items.map((x) => [x.id, x]));
  const ordered: DealDetail[] = [];
  for (const id of ids) {
    const it = map.get(id);
    if (it) ordered.push(it);
  }
  return ordered;
}

function EmptyState({ onPick }: { onPick: () => void }) {
  return (
    <Card elevated className="p-12 text-center relative overflow-hidden">
      <div className="absolute inset-0 bg-gradient-to-b from-primary/5 to-transparent" />
      <div className="relative">
        <div className="inline-flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 ring-1 ring-primary/20 mb-4">
          <GitCompareArrows className="h-5 w-5 text-primary" />
        </div>
        <h3 className="text-lg font-semibold tracking-tight">Compare any two deals side-by-side</h3>
        <p className="text-sm text-muted-foreground mt-2 max-w-md mx-auto leading-relaxed">
          Executive, Returns, Leverage, Risk, Market, Sponsor, Underwriting presets — or build your own. Highlight winners, show deltas vs a baseline, or normalize across the group.
        </p>
        <Button className="mt-6" onClick={onPick}>
          <Plus className="h-4 w-4" />
          Pick deals
        </Button>
      </div>
    </Card>
  );
}

function OneDealState({ dealName, onPick }: { dealName: string; onPick: () => void }) {
  return (
    <Card elevated className="p-12 text-center">
      <div className="text-sm font-medium">Add at least one more deal to compare against <span className="text-primary">{dealName}</span>.</div>
      <Button className="mt-5" size="sm" onClick={onPick}>
        <Plus className="h-4 w-4" />
        Pick deals
      </Button>
    </Card>
  );
}
