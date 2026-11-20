import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import "./refinements.css";
import { ThemeScript } from "@/components/theme-provider";
import { Workspace } from "@/components/workspace";

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
  title: "Kenyon - Deal Analyzer",
  description: "Institutional-grade real estate deal analysis and portfolio tracking.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f3f6fa" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0b10" },
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
      <body className="role-viewer min-h-screen bg-background" data-role="viewer">
        <Workspace>{children}</Workspace>
        <noscript>Enable JavaScript to open this workspace.</noscript>
      </body>
    </html>
  );
}
