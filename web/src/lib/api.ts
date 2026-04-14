/**
 * Thin fetch wrapper for the FastAPI backend.
 *
 * Server components call the backend directly via `FASTAPI_URL` (internal
 * network). Client components hit `/api/...` on the same origin, which
 * Next.js rewrites route to the backend.
 */

const INTERNAL_BASE = process.env.FASTAPI_URL || "http://127.0.0.1:8000";

/** Base URL to use for a request depending on execution environment. */
function baseUrl(): string {
  if (typeof window === "undefined") return INTERNAL_BASE;
  return "";
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
  const res = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
    next: typeof window === "undefined" ? { revalidate: revalidate === false ? false : revalidate } : undefined,
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
