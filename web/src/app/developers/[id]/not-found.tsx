import Link from "next/link";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Building2 } from "lucide-react";

export default function DeveloperNotFound() {
  return (
    <div className="max-w-xl mx-auto px-6 py-24 text-center">
      <Card elevated className="p-12">
        <div className="inline-flex h-11 w-11 items-center justify-center rounded-xl bg-muted ring-1 ring-border mb-4">
          <Building2 className="h-5 w-5 text-muted-foreground" />
        </div>
        <h1 className="text-display tracking-tight">Developer not found</h1>
        <p className="text-sm text-muted-foreground mt-2">
          This sponsor may have been deleted, or the link is wrong.
        </p>
        <Button asChild className="mt-6">
          <Link href="/developers">Back to developers</Link>
        </Button>
      </Card>
    </div>
  );
}
