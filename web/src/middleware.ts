import { NextResponse, type NextRequest } from "next/server";

/**
 * Client-side auth gate.
 *
 * The backend is the source of truth; this middleware is just a
 * first-pass redirect so users don't see a flash of unauthenticated UI.
 * It looks for the `kenyon_session` cookie. If the cookie is absent on
 * a protected page route, it redirects to `/login?next=<current>`.
 *
 * API requests intentionally bypass this middleware. FastAPI validates
 * those calls and returns JSON errors; redirecting an API upload to the
 * login page turns real upload/auth failures into vague browser errors.
 */

const PUBLIC_PAGES = ["/login", "/legacy"];
const PUBLIC_PREFIXES = [
  "/_next/",
  "/favicon.ico",
  "/api/",
  "/document-upload/",
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

  // We don't talk to the backend from middleware: too slow, too flaky.
  // Presence of the cookie is enough to avoid a visual login flash; if the
  // session is expired, the backend will reject API calls and the client will
  // handle that response explicitly.
  const cookie = req.cookies.get("kenyon_session");
  if (cookie?.value) {
    return NextResponse.next();
  }

  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.searchParams.set("next", pathname + (req.nextUrl.search || ""));
  return NextResponse.redirect(url);
}

export const config = {
  // Match application pages only. API and upload paths return JSON errors.
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|login|api|document-upload|legacy|static).*)",
  ],
};
