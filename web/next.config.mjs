/** @type {import('next').NextConfig} */
const FASTAPI = process.env.FASTAPI_URL || "http://127.0.0.1:8000";

/**
 * Content-Security-Policy. Tight but permissive enough for:
 *   - MapLibre tiles (CARTO basemaps, Esri World Imagery, OSM tiles)
 *   - The inline ThemeScript (pre-hydration class toggle) — uses
 *     'unsafe-inline' for script-src because coordinating a nonce
 *     across Next.js RSC + inline script is more trouble than the
 *     defense-in-depth is worth for a single-user tool.
 *   - next/font inlines fonts via CSS @font-face, no external fetch.
 */
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  // MapLibre fetches PNG tiles from these origins; data: for inline icons.
  "img-src 'self' data: blob:" +
    " https://*.basemaps.cartocdn.com" +
    " https://server.arcgisonline.com" +
    " https://*.tile.openstreetmap.org" +
    " https://*.arcgis.com",
  // Workers used by MapLibre for tile decoding
  "worker-src 'self' blob:",
  // Fonts via data: (next/font), self-hosted
  "font-src 'self' data:",
  // Nothing else should open a network connection from the browser
  "connect-src 'self' https://*.basemaps.cartocdn.com https://server.arcgisonline.com",
  // No popups, no frames
  "frame-ancestors 'none'",
  "form-action 'self'",
  "base-uri 'self'",
  "object-src 'none'",
].join("; ");

const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: CSP },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
  },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  {
    key: "Strict-Transport-Security",
    value: "max-age=31536000; includeSubDomains",
  },
];

const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,

  async headers() {
    return [
      {
        // Apply to every UI route. The legacy pass-through inherits too
        // but that's fine — same policy is valid there.
        source: "/:path*",
        headers: SECURITY_HEADERS,
      },
    ];
  },

  // Proxy API calls, legacy UI, and legacy static assets to the FastAPI
  // backend. Same origin in the browser so cookies/auth work without
  // CORS gymnastics.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${FASTAPI}/api/:path*` },
      { source: "/legacy", destination: `${FASTAPI}/legacy` },
      { source: "/legacy/:path*", destination: `${FASTAPI}/legacy/:path*` },
      { source: "/static/:path*", destination: `${FASTAPI}/static/:path*` },
    ];
  },
};

export default nextConfig;
