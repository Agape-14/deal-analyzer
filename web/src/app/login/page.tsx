"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2, Lock, Sparkles } from "lucide-react";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";

/**
 * Login page. Pre-fills `username = "admin"` since that's the only user.
 * After a successful login we redirect to `?next=` (set by middleware)
 * or `/` as a fallback.
 */
export default function LoginPage() {
  const router = useRouter();
  const search = useSearchParams();
  const next = search?.get("next") || "/";
  const [username, setUsername] = React.useState("admin");
  const [password, setPassword] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [authDisabled, setAuthDisabled] = React.useState<boolean | null>(null);

  // If auth is disabled on the server, skip straight through.
  React.useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.auth_disabled) {
          setAuthDisabled(true);
          router.replace(next);
        } else if (d?.authenticated) {
          router.replace(next);
        } else {
          setAuthDisabled(false);
        }
      })
      .catch(() => setAuthDisabled(false));
  }, [next, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!password.trim()) return;
    setSubmitting(true);
    try {
      await api.post("/api/auth/login", { username, password });
      toast.success("Welcome back");
      router.replace(next);
    } catch (err) {
      const d = (err as { detail?: string })?.detail ?? "Login failed";
      toast.error(d);
    } finally {
      setSubmitting(false);
    }
  }

  // While we probe /api/auth/me, show an empty shell — prevents the
  // "flash of login page" when the user is already signed in.
  if (authDisabled === null) {
    return (
      <div className="min-h-screen bg-background grid place-items-center">
        <Loader2 className="h-5 w-5 text-muted-foreground animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background relative overflow-hidden">
      {/* Ambient radial */}
      <div aria-hidden className="pointer-events-none absolute inset-0 bg-radial-fade" />

      <div className="relative min-h-screen grid place-items-center p-6">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
          className="w-full max-w-sm"
        >
          {/* Brand */}
          <div className="flex items-center gap-2.5 mb-8">
            <div className="h-9 w-9 rounded-lg bg-gradient-to-br from-primary to-chart-3 shadow-[0_8px_24px_-8px_hsl(var(--primary)/.6)] grid place-items-center">
              <Sparkles className="h-4 w-4 text-primary-foreground" />
            </div>
            <div className="leading-tight">
              <div className="text-sm font-semibold tracking-tight">Kenyon</div>
              <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                Deal Analyzer
              </div>
            </div>
          </div>

          <Card elevated className="p-6">
            <div className="flex items-center gap-2 mb-1">
              <Lock className="h-4 w-4 text-muted-foreground" />
              <h1 className="text-lg font-semibold tracking-tight">Sign in</h1>
            </div>
            <p className="text-xs text-muted-foreground mb-6">
              Single-user access. Use the credentials configured on the server.
            </p>

            <form onSubmit={submit} className="space-y-4">
              <div className="space-y-2">
                <Label>Username</Label>
                <Input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                  disabled={submitting}
                />
              </div>
              <div className="space-y-2">
                <Label>Password</Label>
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  autoFocus
                  disabled={submitting}
                  required
                />
              </div>
              <Button type="submit" className="w-full mt-2" disabled={submitting || !password}>
                {submitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Lock className="h-4 w-4" />
                )}
                Sign in
              </Button>
            </form>
          </Card>

          <div className="text-[10px] text-muted-foreground mt-5 text-center leading-relaxed">
            Session lasts 30 days. Configure <code className="font-mono">AUTH_USERNAME</code> and{" "}
            <code className="font-mono">AUTH_PASSWORD_HASH</code> on the server.
          </div>
        </motion.div>
      </div>
    </div>
  );
}
