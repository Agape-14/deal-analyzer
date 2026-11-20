"use client";
import * as React from "react";
import { api } from "./api";

type Health = { status: string; environment?: Record<string, { configured?: boolean; message?: string | null; affects?: string[] }>; release?: { backend_commit: string; schema: string } };
const Context = React.createContext<{ health: Health | null; refresh: () => void }>({ health: null, refresh: () => {} });

export function CapabilityProvider({ children }: { children: React.ReactNode }) {
  const [health, setHealth] = React.useState<Health | null>(null);
  const [retry, refresh] = React.useReducer(n => n + 1, 0);
  React.useEffect(() => {
    let active = true;
    api.get<Health>("/api/healthz").then(data => { if (active) setHealth(data); }).catch(() => { if (active) setHealth(null); });
    return () => { active = false; };
  }, [retry]);
  return <Context.Provider value={{ health, refresh }}>{children}</Context.Provider>;
}

export function useCapabilities() {
  const { health, refresh } = React.useContext(Context);
  const creditReview = health?.environment?.openai;
  const codexOnly = !!health?.environment?.codex;
  const configuredReview = creditReview ?? health?.environment?.anthropic;
  const review = codexOnly || configuredReview?.configured === false ? "unavailable" : health ? "configured" : "unknown";
  return { health, refresh, creditReview: !!creditReview, codexFirst: codexOnly || !!creditReview || review === "unavailable",
    reviewMessage: codexOnly ? null : configuredReview?.message, review };
}
