import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Suspense } from "react";
import { AppShell } from "@/components/app-shell";
import { CommandPalette } from "@/components/command-palette";
import { NewDealDrawer } from "@/components/new-deal-drawer";
import { ThemeProvider, ThemeScript } from "@/components/theme-provider";
import { HelpHotkey, FirstRunWelcome } from "@/components/help-overlay";
import { Toaster } from "sonner";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "Kenyon — Deal Analyzer",
  description: "Institutional-grade real estate deal analysis and portfolio tracking.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0a0b10" },
    { media: "(prefers-color-scheme: light)", color: "#f7fafc" },
  ],
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        {/* ThemeScript runs before React to set the class on <html> and
            prevent a flash of the wrong theme. Must be in <head>. */}
        <ThemeScript />
      </head>
      <body className="min-h-screen bg-background">
        <ThemeProvider>
          {/* Subtle radial highlight behind the main content */}
          <div aria-hidden className="pointer-events-none fixed inset-0 bg-radial-fade" />
          <AppShell>{children}</AppShell>
          <CommandPalette />
          <HelpHotkey />
          <FirstRunWelcome />
          <Suspense fallback={null}>
            <NewDealDrawer />
          </Suspense>
          <Toaster
            position="bottom-right"
            theme="dark"
            richColors
            closeButton
            toastOptions={{
              style: {
                background: "#1a1d24",
                border: "1px solid #2a2e38",
                color: "#f5f5f7",
              },
            }}
          />
        </ThemeProvider>
      </body>
    </html>
  );
}
