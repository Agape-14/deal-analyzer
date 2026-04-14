import { NextResponse, type NextRequest } from "next/server";

/**
 * Client-side auth gate.
 *
 * The backend is the source of truth; this middleware is just a
 * first-pass redirect so users don't see a flash of unauthenticated UI.
 * It looks for the `kenyon_session` cookie. If the cookie is absent on
 * a protected route, it redirects to `/login?next=<current>`. The
 * backend still validates every API call — this is convenience, not
 * security.
 */

// Paths that must NEVER require auth. Keep narrow.
const PUBLIC_PAGES = ["/login", "/legacy"];
const PUBLIC_PREFIXES = [
  "/_next/",
  "/favicon.ico",
  "/api/auth/",
  "/api/healthz",
  "/static/",
];

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (
    PUBLIC_PAGES.includes(pathname) ||
    PUBLIC_PREFIXES.some((p) => pathname.startsWith(p))
  ) {
    return NextResponse.next();
  }

  // We don't talk to the backend from middleware — too slow, too flaky.
  // Presence of the cookie is a good-enough indicator to skip the
  // redirect; if the cookie is expired the backend will 401 and the
  // client will handle that.
  const cookie = req.cookies.get("kenyon_session");
  if (cookie?.value) {
    return NextResponse.next();
  }

  // No cookie → kick to /login keeping the destination in a ?next param
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.searchParams.set("next", pathname + (req.nextUrl.search || ""));
  return NextResponse.redirect(url);
}

export const config = {
  // Match everything except Next's own static assets and API proxy paths
  // that the backend must be allowed to answer (auth endpoints).
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|login|api/auth|api/healthz|legacy|static).*)",
  ],
};
