"use client";

import * as React from "react";
import { useCurrentUser } from "@/lib/auth-client";

export function RoleBodyClass() {
  const { role, loading } = useCurrentUser();

  React.useEffect(() => {
    if (loading) return;
    const resolvedRole = role ?? "viewer";
    document.body.dataset.role = resolvedRole;
    document.body.classList.toggle("role-admin", resolvedRole === "admin" || resolvedRole === "analyst");
    document.body.classList.toggle("role-viewer", resolvedRole === "viewer");
    return () => {
      delete document.body.dataset.role;
      document.body.classList.remove("role-admin", "role-viewer");
    };
  }, [loading, role]);

  return null;
}
