"use client";

import * as React from "react";
import { Search, Plus, Command } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MobileNav } from "@/components/app-sidebar";
import { ThemeToggle } from "@/components/theme-toggle";
import { HelpButton } from "@/components/help-overlay";
import { NotificationsBell } from "@/components/notifications-bell";

/**
 * Minimal header. Search placeholder triggers command palette (⌘K).
 * On mobile (<md) a hamburger appears at the left; the sidebar is hidden
 * because it doesn't fit.
 */
export function AppHeader() {
  return (
    <header className="sticky top-0 z-30 h-16 border-b border-border/60 bg-background/80 backdrop-blur-md">
      <div className="h-full flex items-center gap-3 px-4 md:px-6">
        <MobileNav />
        <button
          className="group flex items-center gap-2 h-9 px-3 rounded-md border border-border/80 bg-secondary/40 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/70 transition-colors flex-1 md:flex-none md:w-80"
          onClick={() => document.dispatchEvent(new CustomEvent("open-command-palette"))}
        >
          <Search className="h-4 w-4" />
          <span className="flex-1 text-left truncate">Search deals, developers…</span>
          <kbd className="hidden sm:inline-flex items-center gap-0.5 text-[10px] font-mono text-muted-foreground border border-border/80 rounded px-1.5 py-0.5 bg-background/40">
            <Command className="h-2.5 w-2.5" />K
          </kbd>
        </button>
        <div className="hidden md:block flex-1" />
        <NotificationsBell />
        <HelpButton />
        <ThemeToggle />
        <Button
          variant="default"
          size="sm"
          onClick={() => document.dispatchEvent(new CustomEvent("open-new-deal"))}
        >
          <Plus className="h-4 w-4" />
          <span className="hidden sm:inline">New Deal</span>
        </Button>
      </div>
    </header>
  );
}
