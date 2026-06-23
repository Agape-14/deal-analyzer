"use client";

import * as React from "react";
import { isAnalystRole, useCurrentUser } from "@/lib/auth-client";

export function RoleBodyClass() {
  const { role, loading } = useCurrentUser();

  React.useEffect(() => {
    if (loading) return;
    const resolvedRole = role ?? "viewer";
    const isAnalyst = isAnalystRole(resolvedRole);
    document.body.dataset.role = resolvedRole;
    document.body.classList.toggle("role-admin", isAnalyst);
    document.body.classList.toggle("role-viewer", resolvedRole === "viewer");

    if (isAnalyst) {
      document
        .querySelectorAll<HTMLDetailsElement>("details#analyst-tools, details#analyst-review")
        .forEach((section) => {
          section.open = true;
        });
    }

    return () => {
      delete document.body.dataset.role;
      document.body.classList.remove("role-admin", "role-viewer");
    };
  }, [loading, role]);

  return null;
}
