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
const BAD_SOURCE_STATUSES = new Set(["wrong", "missing", "unverifiable", "stale", "math_failed"]);
const REVIEWED_SOURCE_STATUSES = new Set(["manual", "confirmed", "calculated"]);

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

/** Shape thrown from `api.*` on non-2xx responses. */
interface ApiError {
  status: number;
  detail: string;
}

type BatchFieldEditBody = {
  edits?: Array<{
    path: string;
    value?: unknown;
    lock?: boolean;
  }>;
};

type ProvenanceLike = {
  status?: unknown;
  conflict?: unknown;
  locked?: unknown;
  source?: unknown;
};

type MetricsLike = {
  target_returns?: Record<string, unknown>;
  _provenance?: Record<string, ProvenanceLike>;
};

type DealLike = {
  metrics?: MetricsLike;
  target_irr?: unknown;
  target_equity_multiple?: unknown;
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
  return normalizeApiPayload(await res.json()) as T;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  if (path.endsWith("/fields/batch-edit")) {
    const batch = body as BatchFieldEditBody | undefined;
    const edits = Array.isArray(batch?.edits) ? batch.edits : [];
    const basePath = path.replace(/\/fields\/batch-edit$/, "/fields/edit");
    const results = [];
    for (const edit of edits) {
      results.push(await request(basePath, { method: "POST", body: JSON.stringify(edit) }));
    }
    return { message: "Fields updated", results } as T;
  }
  return request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
}

function normalizeApiPayload(payload: unknown): unknown {
  if (Array.isArray(payload)) return payload.map(normalizeDealSummary);
  if (!isRecord(payload)) return payload;
  if (Array.isArray(payload.deals)) return { ...payload, deals: payload.deals.map(normalizeDealSummary) };
  return normalizeDealSummary(payload);
}

function normalizeDealSummary(value: unknown): unknown {
  if (!isRecord(value) || !isRecord(value.metrics)) return value;
  const deal = value as DealLike;
  const targetIrr = pickReturnMetric(deal.metrics, ["target_returns.target_irr", "target_returns.net_irr"]);
  const targetMultiple = pickReturnMetric(deal.metrics, [
    "target_returns.target_equity_multiple",
    "target_returns.net_equity_multiple",
  ]);
  return {
    ...value,
    target_irr: targetIrr ?? deal.target_irr,
    target_equity_multiple: targetMultiple ?? deal.target_equity_multiple,
  };
}

function pickReturnMetric(metrics: MetricsLike | undefined, paths: string[]): unknown {
  const returns = metrics?.target_returns ?? {};
  const provenance = metrics?._provenance ?? {};
  const candidates = paths
    .map((path) => ({ path, value: returns[path.split(".").at(-1) ?? path], provenance: provenance[path] }))
    .filter((candidate) => candidate.value !== null && candidate.value !== undefined && candidate.value !== "");

  if (candidates.length === 0) return null;
  const clean = candidates.filter((candidate) => !isBadSource(candidate.provenance));
  const reviewed = clean.find((candidate) => {
    const status = String(candidate.provenance?.status ?? "").toLowerCase();
    return Boolean(candidate.provenance?.locked) || String(candidate.provenance?.source ?? "").toLowerCase() === "manual" || REVIEWED_SOURCE_STATUSES.has(status);
  });
  return (reviewed ?? clean[0] ?? candidates[0]).value;
}

function isBadSource(provenance?: ProvenanceLike): boolean {
  if (!provenance) return false;
  const status = String(provenance.status ?? "").toLowerCase();
  const conflictCount = Array.isArray(provenance.conflict) ? provenance.conflict.length : 0;
  return conflictCount > 1 || BAD_SOURCE_STATUSES.has(status);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export const api = {
  get: <T>(path: string, opts?: { revalidate?: number | false }) =>
    request<T>(path, { method: "GET" }, opts?.revalidate ?? 0),
  post: postJson,
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
