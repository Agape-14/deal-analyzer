"use client";

import { AlertTriangle, CheckCircle2, Clock3, HelpCircle, ShieldAlert, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import type { DataQualityGate } from "@/lib/types";

type BadgeSize = "sm" | "md";

export function ScoreQualityBadge({
  gate,
  size = "md",
  className,
}: {
  gate?: DataQualityGate;
  size?: BadgeSize;
  className?: string;
}) {
  const ui = stageUi(gate?.stage, gate?.can_score);
  const Icon = ui.Icon;
  const detail = gate?.confidence_score != null ? `${gate.confidence_score}% confidence` : ui.detail;

  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full font-medium ring-1",
        size === "sm" ? "px-2 py-0.5 text-[10px] uppercase tracking-wider" : "px-2.5 py-1 text-xs",
        ui.className,
        className,
      )}
      title={detail}
    >
      <Icon className={size === "sm" ? "h-3 w-3" : "h-3.5 w-3.5"} />
      {ui.label}
      {size === "md" && detail && <span className="hidden sm:inline opacity-80">· {detail}</span>}
    </div>
  );
}

export function scoreStageLabel(stage?: string | null): string {
  return stageUi(stage, undefined).label;
}

function stageUi(stage: string | null | undefined, canScore: boolean | undefined) {
  if (stage === "verified" || canScore) {
    return {
      Icon: ShieldCheck,
      label: "Verified",
      detail: "Source-backed and score-ready",
      className: "bg-success/15 text-success ring-success/30",
    };
  }
  switch (stage) {
    case "math_failed":
      return {
        Icon: AlertTriangle,
        label: "Math issue",
        detail: "Score blocked by failed deterministic checks",
        className: "bg-destructive/15 text-destructive ring-destructive/30",
      };
    case "conflicting":
      return {
        Icon: ShieldAlert,
        label: "Conflict",
        detail: "Source documents disagree",
        className: "bg-destructive/15 text-destructive ring-destructive/30",
      };
    case "insufficient_source":
      return {
        Icon: HelpCircle,
        label: "Blocked",
        detail: "Missing or unverifiable critical fields",
        className: "bg-destructive/15 text-destructive ring-destructive/30",
      };
    case "needs_review":
      return {
        Icon: ShieldAlert,
        label: "Needs review",
        detail: "Human review needed before relying on score",
        className: "bg-warning/15 text-warning ring-warning/30",
      };
    case "provisional":
      return {
        Icon: Clock3,
        label: "Provisional",
        detail: "Extracted but not fully verified",
        className: "bg-warning/15 text-warning ring-warning/30",
      };
    default:
      return {
        Icon: CheckCircle2,
        label: "Pending",
        detail: "Waiting for pipeline results",
        className: "bg-muted text-muted-foreground ring-border",
      };
  }
}
