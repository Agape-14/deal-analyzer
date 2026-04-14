"use client";

import * as React from "react";
import { AlertTriangle, X } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";

type EnvStatus = {
  status: "ok" | "degraded" | string;
  environment?: Record<
    string,
    {
      configured?: boolean;
      message?: string | null;
      affects?: string[];
    }
  >;
};

const DISMISS_KEY = "env-banner.dismissed";

/**
 * Top-of-page banner that surfaces environment issues reported by
 * /api/healthz. Rendered in the root layout so every page sees it.
 *
 * The user can dismiss a specific warning (keyed by its affected
 * services) for the session; the banner reappears on a new warning set.
 */
export function EnvironmentBanner() {
  const [status, setStatus] = React.useState<EnvStatus | null>(null);
  const [dismissed, setDismissed] = React.useState<Set<string>>(new Set());

  // Load dismissed set from sessionStorage (so it resets each tab session).
  React.useEffect(() => {
    try {
      const raw = sessionStorage.getItem(DISMISS_KEY);
      if (raw) setDismissed(new Set(JSON.parse(raw)));
    } catch {
      /* ignore */
    }
  }, []);

  React.useEffect(() => {
    fetch("/api/healthz")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setStatus(d))
      .catch(() => {
        // If healthz is unreachable the rest of the app will surface it
        // as 500s on real endpoints; don't spam an extra banner.
      });
  }, []);

  if (!status || status.status === "ok" || !status.environment) return null;

  const warnings = Object.entries(status.environment)
    .filter(([, info]) => info && !info.configured && info.message)
    .map(([service, info]) => ({ service, ...info }));
  if (warnings.length === 0) return null;

  const key = warnings.map((w) => w.service).sort().join(",");
  if (dismissed.has(key)) return null;

  function dismiss() {
    const next = new Set(dismissed);
    next.add(key);
    setDismissed(next);
    try {
      sessionStorage.setItem(DISMISS_KEY, JSON.stringify([...next]));
    } catch {
      /* ignore */
    }
  }

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.2 }}
        className={cn(
          "relative w-full border-b border-warning/40 bg-warning/10 text-warning",
          "px-4 md:px-6 py-2.5 text-xs",
        )}
        role="alert"
      >
        <div className="max-w-[1400px] mx-auto flex items-start gap-3">
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
          <div className="flex-1 leading-relaxed">
            <div className="font-medium mb-0.5">
              Backend is running in a degraded configuration.
            </div>
            <ul className="list-disc list-inside space-y-0.5 text-warning/90">
              {warnings.map((w) => (
                <li key={w.service}>{w.message}</li>
              ))}
            </ul>
          </div>
          <button
            onClick={dismiss}
            aria-label="Dismiss"
            className="shrink-0 rounded-md p-1 hover:bg-warning/20 transition-colors"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
