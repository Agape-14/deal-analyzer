/**
 * Thin fetch wrapper for the FastAPI backend.
 *
 * - Client-side: hits `/api/...` on the same origin; browser automatically
 *   sends the session cookie. We opt into `credentials: "include"` so the
 *   browser attaches cookies even on same-origin XHR (defensive).
 * - Server-side (RSC / route handlers / layouts): hits INTERNAL_BASE and
 *   forwards the inbound request's session cookie so the backend can
 *   recognize the user. Without this, server-rendered pages would always
 *   look unauthenticated even when the user is signed in.
 */

const INTERNAL_BASE = process.env.FASTAPI_URL || "http://127.0.0.1:8000";

function baseUrl(): string {
  if (typeof window === "undefined") return INTERNAL_BASE;
  return "";
}

/** Retrieve the Cookie header to forward on server-side requests. */
async function forwardedCookieHeader(): Promise<string | null> {
  if (typeof window !== "undefined") return null;
  try {
    // Dynamic import keeps this path client-bundle-free.
    const { cookies } = await import("next/headers");
    const store = await cookies();
    const all = store.getAll();
    if (!all.length) return null;
    return all.map((c) => `${c.name}=${c.value}`).join("; ");
  } catch {
    // `cookies()` throws outside a request scope; fall back silently.
    return null;
  }
}

export type ApiError = {
  status: number;
  detail: string;
};

async function request<T>(
  path: string,
  init: RequestInit = {},
  revalidate: number | false = 0,
): Promise<T> {
  const url = path.startsWith("/") ? `${baseUrl()}${path}` : path;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string> | undefined),
  };
  const cookieHeader = await forwardedCookieHeader();
  if (cookieHeader) headers["Cookie"] = cookieHeader;

  const res = await fetch(url, {
    ...init,
    headers,
    credentials: "include",
    next:
      typeof window === "undefined"
        ? { revalidate: revalidate === false ? false : revalidate }
        : undefined,
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* body wasn't JSON */
    }
    throw { status: res.status, detail } satisfies ApiError;
  }

  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") || "";
  if (!ct.includes("application/json")) return (await res.blob()) as unknown as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string, opts?: { revalidate?: number | false }) =>
    request<T>(path, { method: "GET" }, opts?.revalidate ?? 0),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

/**
 * On any 401 from the API, kick the user to /login with a ?next param
 * so they return to what they were doing. Call this from your click
 * handlers when you want that behavior.
 */
export function handleAuthError(err: unknown) {
  if (typeof window === "undefined") return;
  if ((err as { status?: number } | null)?.status === 401) {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.replace(`/login?next=${next}`);
  }
}
