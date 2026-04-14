"use client";

import { usePathname } from "next/navigation";
import { AppSidebar } from "@/components/app-sidebar";
import { AppHeader } from "@/components/app-header";
import { EnvironmentBanner } from "@/components/environment-banner";

/**
 * Wraps the app in its chrome (sidebar + header + env banner) for
 * every route EXCEPT the login screen, which renders edge-to-edge.
 *
 * Kept as a client component so we can read the current pathname.
 * The root layout stays server-side so SEO meta works normally.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const chromeless = pathname === "/login";

  if (chromeless) return <>{children}</>;

  return (
    <div className="relative flex min-h-screen">
      <AppSidebar />
      <div className="flex-1 md:ml-60 flex flex-col min-w-0">
        <AppHeader />
        <EnvironmentBanner />
        <main className="flex-1">{children}</main>
      </div>
    </div>
  );
}
