"use client";

import * as React from "react";
import { Moon, Sun, Monitor } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useTheme } from "@/components/theme-provider";
import { cn } from "@/lib/utils";

/**
 * Three-way theme switcher. The dropdown shows Light / Dark / System
 * and the current selection is highlighted.
 */
export function ThemeToggle() {
  const { theme, resolved, setTheme } = useTheme();
  const [open, setOpen] = React.useState(false);

  const Icon = resolved === "dark" ? Moon : Sun;

  return (
    <div className="relative">
      <button
        type="button"
        aria-label="Change theme"
        onClick={() => setOpen((o) => !o)}
        onBlur={() => setTimeout(() => setOpen(false), 140)}
        className="inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
      >
        <Icon className="h-4 w-4" />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.96 }}
            transition={{ duration: 0.12 }}
            className="absolute right-0 top-full mt-1.5 w-40 rounded-lg border border-border/80 bg-card shadow-[0_20px_60px_-20px_rgba(0,0,0,0.9)] p-1 z-30"
          >
            {[
              { key: "light", label: "Light", icon: Sun },
              { key: "dark", label: "Dark", icon: Moon },
              { key: "system", label: "System", icon: Monitor },
            ].map((opt) => (
              <button
                key={opt.key}
                onMouseDown={(e) => {
                  e.preventDefault();
                  setTheme(opt.key as "light" | "dark" | "system");
                  setOpen(false);
                }}
                className={cn(
                  "w-full flex items-center gap-2 px-2.5 h-8 rounded-md text-xs transition-colors",
                  theme === opt.key
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted/60",
                )}
              >
                <opt.icon className="h-3.5 w-3.5" />
                <span className="flex-1 text-left font-medium">{opt.label}</span>
                {theme === opt.key && <span className="text-[10px]">●</span>}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
