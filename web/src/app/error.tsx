"use client";

import * as React from "react";
import { AlertOctagon, RefreshCw, Home } from "lucide-react";
import Link from "next/link";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

/**
 * Root error boundary. Next.js routes any thrown error in a server
 * component or rendered tree here. Gives the user something actionable
 * rather than a white page.
 */
export default function RootError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  React.useEffect(() => {
    // Surface for debugging. In prod a real APM would pick this up.
    // eslint-disable-next-line no-console
    console.error("[kenyon] unhandled error:", error);
  }, [error]);

  return (
    <div className="max-w-xl mx-auto px-6 py-24">
      <Card elevated className="p-10 text-center">
        <div className="inline-flex h-11 w-11 items-center justify-center rounded-xl bg-destructive/10 ring-1 ring-destructive/30 mb-4">
          <AlertOctagon className="h-5 w-5 text-destructive" />
        </div>
        <h1 className="text-display tracking-tight">Something went wrong</h1>
        <p className="text-sm text-muted-foreground mt-2 max-w-md mx-auto leading-relaxed">
          We hit an unexpected error. Try again — if the problem sticks around,
          the backend may be down or misconfigured.
        </p>
        {error?.message && (
          <pre className="mt-4 mx-auto max-w-md text-[11px] font-mono text-left bg-muted/40 border border-border/60 rounded-md p-3 overflow-auto whitespace-pre-wrap text-muted-foreground">
            {error.message}
            {error.digest ? `\n\ndigest: ${error.digest}` : ""}
          </pre>
        )}
        <div className="mt-6 flex items-center justify-center gap-2">
          <Button onClick={() => reset()}>
            <RefreshCw className="h-4 w-4" />
            Try again
          </Button>
          <Button variant="outline" asChild>
            <Link href="/">
              <Home className="h-4 w-4" />
              Back to deals
            </Link>
          </Button>
        </div>
      </Card>
    </div>
  );
}
