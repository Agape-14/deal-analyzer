import Link from "next/link";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Construction } from "lucide-react";
import { FadeIn } from "@/components/motion";

/**
 * Shared "page in progress" panel used by routes we've reserved but not yet
 * rebuilt. Links back to the equivalent legacy page.
 */
export function ComingSoon({
  title,
  description,
  legacyHref,
}: {
  title: string;
  description: string;
  legacyHref: string;
}) {
  return (
    <div className="max-w-3xl mx-auto px-6 md:px-10 py-16">
      <FadeIn>
        <Card elevated className="p-12 text-center relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-b from-primary/5 to-transparent pointer-events-none" />
          <div className="relative">
            <div className="inline-flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 ring-1 ring-primary/20 mb-4">
              <Construction className="h-5 w-5 text-primary" />
            </div>
            <h1 className="text-display tracking-tight">{title}</h1>
            <p className="text-sm text-muted-foreground mt-2 max-w-lg mx-auto leading-relaxed">
              {description}
            </p>
            <div className="flex items-center justify-center gap-3 mt-8">
              <Button variant="outline" asChild>
                <Link href={legacyHref}>Use legacy UI →</Link>
              </Button>
              <Button variant="ghost" asChild>
                <Link href="/">Back to deals</Link>
              </Button>
            </div>
          </div>
        </Card>
      </FadeIn>
    </div>
  );
}
