"use client";

import * as React from "react";

type Theme = "light" | "dark" | "system";

const STORAGE_KEY = "kenyon-theme";

interface ThemeContextValue {
  theme: Theme;
  resolved: "light" | "dark";
  setTheme: (t: Theme) => void;
}

const ThemeContext = React.createContext<ThemeContextValue | null>(null);

/**
 * Theme provider. The dark class is applied to `<html>` directly by an
 * inline script (see `ThemeScript`) to avoid a flash of the wrong
 * theme. This provider is only responsible for keeping React state in
 * sync and reacting to user toggles.
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = React.useState<Theme>("dark");
  const [resolved, setResolved] = React.useState<"light" | "dark">("dark");

  // Read the initial theme the inline script wrote to <html>.
  React.useEffect(() => {
    const stored = (localStorage.getItem(STORAGE_KEY) as Theme | null) ?? "dark";
    setThemeState(stored);
    setResolved(resolveTheme(stored));
  }, []);

  // Follow OS preference when theme = "system"
  React.useEffect(() => {
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setResolved(mq.matches ? "dark" : "light");
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);

  // Apply `dark` class + stored value whenever the resolved theme changes
  React.useEffect(() => {
    const html = document.documentElement;
    if (resolved === "dark") html.classList.add("dark");
    else html.classList.remove("dark");
    html.style.colorScheme = resolved;
  }, [resolved]);

  const setTheme = React.useCallback((t: Theme) => {
    setThemeState(t);
    try {
      localStorage.setItem(STORAGE_KEY, t);
    } catch {
      /* private mode, etc. */
    }
    setResolved(resolveTheme(t));
  }, []);

  const value = React.useMemo(() => ({ theme, resolved, setTheme }), [theme, resolved, setTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = React.useContext(ThemeContext);
  if (!ctx) {
    // Fail soft for components that import this outside a provider (e.g. tests)
    return { theme: "dark" as Theme, resolved: "dark" as const, setTheme: () => {} };
  }
  return ctx;
}

function resolveTheme(t: Theme): "light" | "dark" {
  if (t === "system") {
    if (typeof window === "undefined") return "dark";
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return t;
}

/**
 * Inline script that sets the initial theme on <html> BEFORE React mounts.
 * Without this the page would paint in the default (dark) theme and then
 * flash to light if the user had picked light — jarring.
 *
 * Must be rendered as the first thing inside <head> (see layout.tsx).
 */
export function ThemeScript() {
  const code = `
(function() {
  try {
    var stored = localStorage.getItem('${STORAGE_KEY}') || 'dark';
    var isDark = stored === 'dark' ||
      (stored === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    var html = document.documentElement;
    if (isDark) html.classList.add('dark');
    else html.classList.remove('dark');
    html.style.colorScheme = isDark ? 'dark' : 'light';
  } catch (e) { /* ignore */ }
})();
`.trim();
  return <script dangerouslySetInnerHTML={{ __html: code }} />;
}
