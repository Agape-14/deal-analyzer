"use client";

import * as React from "react";

export type UserRole = "admin" | "analyst" | "viewer";

export type AuthUser = {
  authenticated: boolean;
  username?: string;
  role?: UserRole;
  auth_disabled?: boolean;
  issued_at?: number;
  expires_at?: number;
};

export function isAnalystRole(role?: string | null): boolean {
  return role === "admin" || role === "analyst";
}

type AuthState = { user: AuthUser | null; role: UserRole | undefined; loading: boolean; isAnalyst: boolean; isViewer: boolean };
const AuthContext = React.createContext<AuthState>({ user: null, role: undefined, loading: true, isAnalyst: false, isViewer: false });

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = React.useState<AuthUser | null>(null);

  React.useEffect(() => {
    let alive = true;
    fetch("/api/auth/me", { credentials: "include", cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) {
          return { authenticated: false } as AuthUser;
        }
        return (await response.json()) as AuthUser;
      })
      .then((data) => {
        if (alive) setUser(data);
      })
      .catch(() => {
        if (alive) setUser({ authenticated: false });
      });
    return () => {
      alive = false;
    };
  }, []);

  const role = user?.role ?? (user?.authenticated ? "admin" : undefined);
  const isAnalyst = isAnalystRole(role);

  const value = {
    user,
    role,
    loading: user === null,
    isAnalyst,
    isViewer: role === "viewer",
  };
  return React.createElement(AuthContext.Provider, { value }, children);
}

export function useCurrentUser() {
  return React.useContext(AuthContext);
}
