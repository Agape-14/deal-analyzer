"use client";

import * as React from "react";
import { AppShell } from "./app-shell";
import { CommandPalette } from "./command-palette";
import { NewDealDrawer } from "./new-deal-drawer";
import { RoleBodyClass } from "./role-body-class";
import { ThemeProvider } from "./theme-provider";
import { HelpHotkey, FirstRunWelcome } from "./help-overlay";
import { AuthProvider } from "@/lib/auth-client";
import { CapabilityProvider } from "@/lib/capabilities";
import { Toaster } from "sonner";

/**
 * The authenticated workspace depends on browser state and streamed route data.
 * Hydrate one deterministic placeholder, then mount the workspace. Its DOM is
 * created normally instead of hydrating chrome while React moves streamed nodes.
 * Server components still fetch and authorize route data on the server.
 */
export function Workspace({ children }: { children: React.ReactNode }) {
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);
  if (!mounted) return <div role="status" className="min-h-screen grid place-items-center text-sm text-muted-foreground">Opening your workspace…</div>;

  return <ThemeProvider><AuthProvider><CapabilityProvider>
    <RoleBodyClass />
    <div aria-hidden className="pointer-events-none fixed inset-0 bg-radial-fade" />
    <AppShell>{children}</AppShell>
    <CommandPalette />
    <HelpHotkey />
    <FirstRunWelcome />
    <React.Suspense fallback={null}><NewDealDrawer /></React.Suspense>
    <Toaster position="bottom-right" theme="system" richColors closeButton />
  </CapabilityProvider></AuthProvider></ThemeProvider>;
}
