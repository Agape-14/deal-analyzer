"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

/** Large variant of the deal score ring used in the hero. */
export function BigScoreRing({ value, size = 120 }: { value: number | null; size?: number }) {
  if (value == null) {
    return (
      <div
        className="rounded-full border border-dashed border-border grid place-items-center text-muted-foreground"
        style={{ width: size, height: size }}
      >
        <span className="text-xs">Not scored</span>
      </div>
    );
  }
  const radius = (size - 12) / 2;
  const circumference = 2 * Math.PI * radius;
  const pct = Math.max(0, Math.min(10, value)) / 10;
  const offset = circumference * (1 - pct);
  const color =
    value >= 8
      ? "hsl(var(--success))"
      : value >= 6
        ? "hsl(var(--warning))"
        : "hsl(var(--destructive))";
  const label = value >= 8 ? "Strong" : value >= 6 ? "Mixed" : "Weak";

  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="hsl(var(--border))"
          strokeWidth={6}
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={6}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 1.1, ease: [0.22, 1, 0.36, 1] }}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">
        <div>
          <div className={cn("text-[32px] font-semibold tabular-nums leading-none")} style={{ color }}>
            {value.toFixed(1)}
          </div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground mt-1.5">
            {label}
          </div>
        </div>
      </div>
    </div>
  );
}
