import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { AppSidebar } from "@/components/app-sidebar";
import { AppHeader } from "@/components/app-header";
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
  themeColor: "#0a0b10",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable} dark`} suppressHydrationWarning>
      <body className="min-h-screen bg-background">
        {/* Subtle radial highlight behind the main content */}
        <div aria-hidden className="pointer-events-none fixed inset-0 bg-radial-fade" />
        <div className="relative flex min-h-screen">
          <AppSidebar />
          <div className="flex-1 md:ml-60 flex flex-col min-w-0">
            <AppHeader />
            <main className="flex-1">{children}</main>
          </div>
        </div>
        <Toaster
          position="bottom-right"
          theme="dark"
          toastOptions={{
            style: {
              background: "hsl(var(--card))",
              border: "1px solid hsl(var(--border))",
              color: "hsl(var(--foreground))",
            },
          }}
        />
      </body>
    </html>
  );
}
