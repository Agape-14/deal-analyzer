"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Wallet } from "lucide-react";

/** Header button that opens the "Add Investment" drawer. */
export function AddInvestmentButton() {
  return (
    <Button
      size="sm"
      type="button"
      onClick={() => document.dispatchEvent(new CustomEvent("open-new-investment"))}
    >
      <Plus className="h-4 w-4" />
      Add investment
    </Button>
  );
}

/** Empty-state panel for the portfolio page. */
export function EmptyPortfolio() {
  return (
    <Card elevated className="p-12 text-center relative overflow-hidden">
      <div className="absolute inset-0 bg-gradient-to-b from-primary/5 to-transparent" />
      <div className="relative">
        <div className="inline-flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 ring-1 ring-primary/20 mb-4">
          <Wallet className="h-5 w-5 text-primary" />
        </div>
        <h3 className="text-lg font-semibold tracking-tight">No positions yet</h3>
        <p className="text-sm text-muted-foreground mt-1.5 max-w-md mx-auto">
          Add your first investment to start tracking IRR, DPI, multiples, and distributions over time.
        </p>
        <Button
          className="mt-6"
          onClick={() => document.dispatchEvent(new CustomEvent("open-new-investment"))}
        >
          Add investment
        </Button>
        {/* Link kept for no-JS fallback */}
        <Link href="#" className="sr-only">
          Add investment
        </Link>
      </div>
    </Card>
  );
}
