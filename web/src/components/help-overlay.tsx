"use client";

import * as React from "react";
import Link from "next/link";
import {
  Sparkles,
  Command,
  Keyboard,
  Search,
  Upload,
  MapPin,
  ShieldCheck,
  GitCompareArrows,
  BookOpen,
  ArrowRight,
} from "lucide-react";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const FIRST_RUN_KEY = "kenyon-seen-welcome-v1";

/* ======================= Keyboard shortcuts cheat sheet ======================= */

interface Shortcut {
  keys: string[];
  label: string;
}
interface Section {
  title: string;
  shortcuts: Shortcut[];
}

const SECTIONS: Section[] = [
  {
    title: "Global",
    shortcuts: [
      { keys: ["⌘", "K"], label: "Open command palette (deals, developers, actions)" },
      { keys: ["?"], label: "Open this help" },
      { keys: ["Esc"], label: "Close any drawer, modal, or palette" },
    ],
  },
  {
    title: "Dashboard",
    shortcuts: [
      { keys: ["N"], label: "New Deal (from header button)" },
      { keys: ["Type to search"], label: "The top search bar is the palette — just start typing" },
    ],
  },
  {
    title: "Deal detail",
    shortcuts: [
      { keys: ["Tab"], label: "Next tab in the deal view" },
      { keys: ["→ / ← in popups"], label: "Step through conflict-picker options" },
      { keys: ["Enter in Analyst"], label: "Send chat message · Shift+Enter for newline" },
    ],
  },
];

export function KeyboardShortcutsDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg p-0 overflow-hidden">
        <div className="px-5 py-4 border-b border-border/70">
          <div className="flex items-center gap-3">
            <div className="h-8 w-8 rounded-lg bg-primary/10 ring-1 ring-primary/30 grid place-items-center">
              <Keyboard className="h-4 w-4 text-primary" />
            </div>
            <div>
              <DialogTitle>Keyboard shortcuts</DialogTitle>
              <DialogDescription>Quick ways to get around.</DialogDescription>
            </div>
          </div>
        </div>
        <div className="p-5 max-h-[70vh] overflow-y-auto space-y-5">
          {SECTIONS.map((sec) => (
            <div key={sec.title}>
              <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground mb-2">
                {sec.title}
              </div>
              <div className="space-y-1">
                {sec.shortcuts.map((sc, i) => (
                  <div key={i} className="flex items-center justify-between gap-3 py-1">
                    <span className="text-sm">{sc.label}</span>
                    <span className="flex items-center gap-1 shrink-0">
                      {sc.keys.map((k, j) => (
                        <kbd
                          key={j}
                          className="inline-flex items-center justify-center h-5 min-w-5 px-1.5 text-[10px] font-mono border border-border/80 rounded bg-background/60"
                        >
                          {k}
                        </kbd>
                      ))}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}

/* ======================= First-run welcome ======================= */

export function FirstRunWelcome() {
  const [open, setOpen] = React.useState(false);
  const [step, setStep] = React.useState(0);

  React.useEffect(() => {
    // Only show to brand-new users, and never on /login.
    if (typeof window === "undefined") return;
    if (window.location.pathname.startsWith("/login")) return;
    try {
      if (!localStorage.getItem(FIRST_RUN_KEY)) setOpen(true);
    } catch {
      /* ignore */
    }
  }, []);

  function dismiss() {
    try {
      localStorage.setItem(FIRST_RUN_KEY, String(Date.now()));
    } catch {
      /* ignore */
    }
    setOpen(false);
  }

  const steps: Array<{
    title: string;
    body: string;
    icon: React.ComponentType<{ className?: string }>;
    cta?: React.ReactNode;
  }> = [
    {
      title: "Welcome to Kenyon",
      body:
        "Institutional-grade real-estate deal analysis without the spreadsheet tax. Upload an offering memo, let Claude extract metrics, validate against Burke-style rules, and compare deals head-to-head.",
      icon: Sparkles,
    },
    {
      title: "Command palette",
      body: "Everywhere in the app, press ⌘K (or Ctrl+K) to open the palette. Fuzzy-search every deal and developer, jump to pages, or create things from there.",
      icon: Command,
    },
    {
      title: "Upload an OM",
      body: "Click a deal → Documents → drop a PDF. We run OCR + table extraction automatically. On the Metrics tab you'll see a provenance badge per field so you always know where each value came from.",
      icon: Upload,
    },
    {
      title: "Verify against the source",
      body: "The Data Integrity panel on Overview shows extracted / verified / conflicting / manual counters plus a trust score. Hit Verify against docs for a second-pass AI forensic audit.",
      icon: ShieldCheck,
    },
    {
      title: "Compare & decide",
      body: "The Compare tab has 8 built-in presets and a custom builder. Switch between Values, Winners, Deltas vs baseline, or Normalized views. Export to Excel with one click.",
      icon: GitCompareArrows,
    },
    {
      title: "See the neighborhood",
      body: "Every deal has a Location tab — satellite map, nearby apartments + employers + transit (from OpenStreetMap), and HUD Fair Market Rent context so you can sanity-check proforma rents.",
      icon: MapPin,
    },
  ];

  const total = steps.length;
  const s = steps[step];

  return (
    <Dialog open={open} onOpenChange={(o) => (o ? setOpen(true) : dismiss())}>
      <DialogContent className="max-w-md p-0 overflow-hidden">
        <div className="relative px-6 pt-8 pb-5 bg-gradient-to-b from-primary/10 via-transparent to-transparent">
          <div className="inline-flex h-10 w-10 rounded-xl bg-primary/15 ring-1 ring-primary/40 items-center justify-center mb-3">
            <s.icon className="h-5 w-5 text-primary" />
          </div>
          <DialogTitle className="text-lg">{s.title}</DialogTitle>
          <DialogDescription className="text-sm leading-relaxed text-foreground/80 mt-1">
            {s.body}
          </DialogDescription>
        </div>

        {/* Progress dots */}
        <div className="px-6 pb-2 flex items-center justify-center gap-1.5">
          {steps.map((_, i) => (
            <span
              key={i}
              className={cn(
                "h-1.5 rounded-full transition-all",
                i === step ? "w-6 bg-primary" : "w-1.5 bg-muted",
              )}
            />
          ))}
        </div>

        <div className="px-6 py-4 flex items-center justify-between border-t border-border/70 bg-background/40">
          <button
            onClick={dismiss}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            Skip tour
          </button>
          {step < total - 1 ? (
            <Button size="sm" onClick={() => setStep((s) => s + 1)}>
              Next
              <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          ) : (
            <Button size="sm" onClick={dismiss}>
              Get started
              <Sparkles className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

/* ======================= Keyboard listener ======================= */

export function HelpHotkey() {
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      // Don't intercept while the user is typing in an input / textarea /
      // contenteditable — "?" in a message shouldn't open help.
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      if (e.key === "?" || (e.shiftKey && e.key === "/")) {
        e.preventDefault();
        setOpen(true);
      }
    }
    function onCustom() {
      setOpen(true);
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("open-help", onCustom);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("open-help", onCustom);
    };
  }, []);

  return <KeyboardShortcutsDialog open={open} onOpenChange={setOpen} />;
}

/* ======================= Exported button ======================= */

export function HelpButton() {
  return (
    <button
      onClick={() => document.dispatchEvent(new CustomEvent("open-help"))}
      aria-label="Keyboard shortcuts"
      className="inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
      title="Keyboard shortcuts (?)"
    >
      <Keyboard className="h-4 w-4" />
    </button>
  );
}
