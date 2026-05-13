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
  const confidence = gate?.confidence_score != null ? `${gate.confidence_score}% confidence` : null;
  const reasons = confidenceReasons(gate);
  const detail = [confidence, ...reasons].filter(Boolean).join(" - ") || ui.detail;

  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full font-medium ring-1",
        size === "sm" ? "px-2 py-0.5 text-[10px] uppercase tracking-wider" : "px-2.5 py-1 text-xs",
        ui.className,
        className,
      )}
      title={detail}
      aria-label={`${ui.label}${detail ? `: ${detail}` : ""}`}
    >
      <Icon className={size === "sm" ? "h-3 w-3" : "h-3.5 w-3.5"} />
      {ui.label}
      {size === "md" && confidence && <span className="hidden sm:inline opacity-80">- {confidence}</span>}
    </div>
  );
}

export function scoreStageLabel(stage?: string | null): string {
  return stageUi(stage, undefined).label;
}

function confidenceReasons(gate?: DataQualityGate): string[] {
  if (!gate) return [];
  const reasons: string[] = [];
  const critical = gate.critical_summary;
  if (critical) {
    if (critical.missing) reasons.push(`${critical.missing} missing support`);
    if (critical.bad) reasons.push(`${critical.bad} need correction`);
    if (critical.conflicted) reasons.push(`${critical.conflicted} source conflict${critical.conflicted === 1 ? "" : "s"}`);
    if (critical.unverified) reasons.push(`${critical.unverified} need confirmation`);
    if (critical.review_only) reasons.push(`${critical.review_only} analyst check${critical.review_only === 1 ? "" : "s"}`);
  }
  const math = gate.math_summary;
  if (math) {
    if (math.fail) reasons.push(`${math.fail} number${math.fail === 1 ? "" : "s"} do not tie`);
    if (math.warn) reasons.push(`${math.warn} math warning${math.warn === 1 ? "" : "s"}`);
  }
  const breakdown = gate.confidence_breakdown;
  if (breakdown && reasons.length < 3) {
    if (breakdown.critical_field_score != null) {
      reasons.push(`critical fields ${Math.round(breakdown.critical_field_score)}%`);
    }
    if (breakdown.broad_verification_score != null) {
      reasons.push(`overall verification ${Math.round(breakdown.broad_verification_score)}%`);
    }
  }
  return reasons.slice(0, 4);
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
        label: "Numbers do not tie",
        detail: "Final score held until the review queue items are cleared",
        className: "bg-destructive/15 text-destructive ring-destructive/30",
      };
    case "conflicting":
      return {
        Icon: ShieldAlert,
        label: "Source conflict",
        detail: "Source documents disagree; confirm the correct value",
        className: "bg-destructive/15 text-destructive ring-destructive/30",
      };
    case "insufficient_source":
      return {
        Icon: HelpCircle,
        label: "Missing support",
        detail: "A required field needs a source or manual confirmation",
        className: "bg-destructive/15 text-destructive ring-destructive/30",
      };
    case "needs_review":
      return {
        Icon: ShieldAlert,
        label: "Needs review",
        detail: "Open the review queue to clear the remaining items",
        className: "bg-warning/15 text-warning ring-warning/30",
      };
    case "provisional":
      return {
        Icon: Clock3,
        label: "Checking",
        detail: "Pipeline has extracted data, but verification is not complete",
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
