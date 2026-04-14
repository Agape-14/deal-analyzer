"use client";

import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

export function AddDeveloperButton({ variant = "default" }: { variant?: "default" | "secondary" }) {
  return (
    <Button
      size="sm"
      variant={variant}
      onClick={() => document.dispatchEvent(new CustomEvent("open-new-developer"))}
    >
      <Plus className="h-4 w-4" />
      Add developer
    </Button>
  );
}
