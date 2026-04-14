"use client";

import * as React from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Sparkles,
  Check,
  Eye,
  GitCompareArrows,
  Percent,
  Crown,
  Layers,
  SlidersHorizontal,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { PRESETS } from "./presets";
import type { CompareMode } from "./metrics-table";
import type { DealDetail } from "@/lib/types";
import { cn } from "@/lib/utils";

const MODES: Array<{ key: CompareMode; label: string; icon: React.ComponentType<{ className?: string }> }> = [
  { key: "values", label: "Values", icon: Eye },
  { key: "winners", label: "Winners", icon: Crown },
  { key: "deltas", label: "Deltas", icon: GitCompareArrows },
  { key: "normalized", label: "Normalized", icon: Percent },
];

export function CompareToolbar({
  preset,
  onPreset,
  mode,
  onMode,
  baseline,
  onBaseline,
  deals,
  hasCustom,
  onOpenCustom,
}: {
  preset: string;
  onPreset: (key: string) => void;
  mode: CompareMode;
  onMode: (m: CompareMode) => void;
  baseline: number | null;
  onBaseline: (id: number | null) => void;
  deals: DealDetail[];
  hasCustom: boolean;
  onOpenCustom: () => void;
}) {
  const [baselineOpen, setBaselineOpen] = React.useState(false);

  const visiblePresets = PRESETS.filter((p) => p.key !== "all");
  const activePreset = PRESETS.find((p) => p.key === preset);

  return (
    <div className="space-y-3">
      {/* Presets */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground mr-1">
          Preset
        </span>
        {visiblePresets.map((p) => {
          const active = preset === p.key;
          return (
            <button
              key={p.key}
              onClick={() => onPreset(p.key)}
              title={p.description}
              className={cn(
                "relative px-3 h-8 rounded-full text-xs font-medium transition-colors",
                active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {active && (
                <motion.span
                  layoutId="preset-pill"
                  className="absolute inset-0 rounded-full bg-card ring-1 ring-border/80 shadow-sm"
                  transition={{ type: "spring", stiffness: 420, damping: 32 }}
                />
              )}
              <span className="relative">{p.label}</span>
            </button>
          );
        })}

        {/* All */}
        <button
          onClick={() => onPreset("all")}
          title="Every row we know about."
          className={cn(
            "relative px-3 h-8 rounded-full text-xs font-medium transition-colors",
            preset === "all" ? "text-foreground" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {preset === "all" && (
            <motion.span
              layoutId="preset-pill"
              className="absolute inset-0 rounded-full bg-card ring-1 ring-border/80 shadow-sm"
              transition={{ type: "spring", stiffness: 420, damping: 32 }}
            />
          )}
          <span className="relative">All</span>
        </button>

        {/* Custom */}
        <button
          onClick={() => (hasCustom ? onPreset("custom") : onOpenCustom())}
          className={cn(
            "relative px-3 h-8 rounded-full text-xs font-medium transition-colors inline-flex items-center gap-1",
            preset === "custom" ? "text-foreground" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {preset === "custom" && (
            <motion.span
              layoutId="preset-pill"
              className="absolute inset-0 rounded-full bg-card ring-1 ring-border/80 shadow-sm"
              transition={{ type: "spring", stiffness: 420, damping: 32 }}
            />
          )}
          <Sparkles className="h-3 w-3 relative" />
          <span className="relative">{hasCustom ? "Custom" : "Build your own"}</span>
        </button>

        {hasCustom && (
          <button
            onClick={onOpenCustom}
            className="inline-flex items-center gap-1 px-2.5 h-8 rounded-full text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            <SlidersHorizontal className="h-3 w-3" />
            Edit
          </button>
        )}
      </div>

      {/* Mode + baseline */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">View</span>
        <div className="inline-flex items-center gap-0.5 p-1 rounded-lg bg-secondary/40 border border-border/70">
          {MODES.map((m) => {
            const active = mode === m.key;
            return (
              <button
                key={m.key}
                onClick={() => onMode(m.key)}
                className={cn(
                  "relative flex items-center gap-1.5 px-2.5 h-7 rounded-md text-xs font-medium transition-colors",
                  active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {active && (
                  <motion.span
                    layoutId="mode-pill"
                    className="absolute inset-0 rounded-md bg-card ring-1 ring-border/80 shadow-sm"
                    transition={{ type: "spring", stiffness: 420, damping: 32 }}
                  />
                )}
                <m.icon className="relative h-3 w-3" />
                <span className="relative">{m.label}</span>
              </button>
            );
          })}
        </div>

        {mode === "deltas" && (
          <div className="relative">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setBaselineOpen((o) => !o)}
              onBlur={() => setTimeout(() => setBaselineOpen(false), 120)}
            >
              <Layers className="h-3.5 w-3.5" />
              Baseline:{" "}
              <span className="font-semibold ml-1">
                {baseline ? deals.find((d) => d.id === baseline)?.project_name ?? "—" : "—"}
              </span>
            </Button>
            <AnimatePresence>
              {baselineOpen && (
                <motion.div
                  initial={{ opacity: 0, y: -4, scale: 0.97 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -4, scale: 0.97 }}
                  transition={{ duration: 0.12 }}
                  className="absolute right-0 top-full mt-1.5 w-56 rounded-lg border border-border/80 bg-card shadow-[0_20px_60px_-20px_rgba(0,0,0,0.9)] p-1 z-30"
                >
                  {deals.map((d) => (
                    <button
                      key={d.id}
                      onMouseDown={(e) => {
                        e.preventDefault();
                        onBaseline(d.id);
                        setBaselineOpen(false);
                      }}
                      className={cn(
                        "w-full flex items-center gap-2 px-2.5 h-8 rounded-md text-xs transition-colors",
                        baseline === d.id
                          ? "bg-muted text-foreground"
                          : "text-muted-foreground hover:text-foreground hover:bg-muted/60",
                      )}
                    >
                      <span className="flex-1 text-left font-medium truncate">{d.project_name}</span>
                      {baseline === d.id && <Check className="h-3.5 w-3.5" />}
                    </button>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}

        {activePreset && (
          <span className="text-xs text-muted-foreground ml-auto">
            {activePreset.description}
          </span>
        )}
      </div>
    </div>
  );
}
