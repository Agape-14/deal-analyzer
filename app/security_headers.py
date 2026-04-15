"""
Security response headers middleware.

Applies a conservative set of headers on every response. Defaults are
safe for production behind Railway's TLS-terminating edge; local HTTP
dev is handled by skipping HSTS when the request arrived as plain HTTP.

Header rationale:

  Strict-Transport-Security
    Forces HTTPS for 1 year. Only emitted when the incoming request is
    HTTPS (so `localhost` isn't told to never downgrade).

  X-Content-Type-Options: nosniff
    Stops browsers from MIME-sniffing JSON as HTML, which would open
    an XSS vector if we ever accidentally returned user content with
    an html-ish payload.

  X-Frame-Options: DENY
    No frame embedding. Also covered by `frame-ancestors 'none'` in
    CSP, but XFO is broader browser support.

  Referrer-Policy: strict-origin-when-cross-origin
    Don't leak the full URL (which may include ?tab=analyst or
    ?ids=1,2,3) to third-party sites when users click outbound links.

  Permissions-Policy
    Declare we don't need camera / mic / geolocation / payment APIs.
    Prevents injected iframes / scripts from prompting.

  Cross-Origin-Opener-Policy: same-origin
    Opts into origin isolation (defeats Spectre-style side channels
    across tabs). Safe because we don't open popups that rely on
    cross-origin window handles.

  Content-Security-Policy
    Set by the Next.js layer (next.config.mjs) on UI routes where we
    know which external origins the map tiles use. Not set here on
    API responses — they're JSON and the browser never renders them.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        h = response.headers
        # Only add HSTS if the original scheme was HTTPS. Behind a
        # proxy, the upstream scheme comes through as X-Forwarded-Proto.
        scheme = (
            request.headers.get("x-forwarded-proto")
            or request.url.scheme
            or ""
        ).lower()
        if scheme == "https":
            h.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        return response
